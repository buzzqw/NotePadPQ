import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from core import secrets as secret_store
from plugins.ai_plugin import _AIPanel, _AIWorker
from plugins.ftp_browser_plugin import FtpProfile, _FtpOpWorker, _FtpPanel
from plugins.git_plugin import _save_token
from plugins.plugin_manager import PluginManager
from plugins.rest_client_plugin import (
    EnvProfile,
    HttpRequest,
    _RestPanel,
    _safe_pre_request_variables,
    _safe_test_results,
)


class SecretStorageTest(unittest.TestCase):
    def test_set_secret_never_falls_back_to_settings(self):
        keyring = types.SimpleNamespace(
            set_password=mock.Mock(side_effect=RuntimeError("unavailable")),
        )
        settings = mock.Mock()
        with mock.patch.dict(sys.modules, {"keyring": keyring}):
            with mock.patch("config.settings.Settings.instance", return_value=settings):
                with self.assertRaises(secret_store.SecretStorageUnavailable):
                    secret_store.set_secret("ai/openai_key", "secret")
        settings.set.assert_not_called()


class RestSecurityTest(unittest.TestCase):
    class _Items:
        def clear(self):
            pass

        def addItem(self, _item):
            pass

    def _panel(self, path: Path):
        panel = _RestPanel.__new__(_RestPanel)
        panel._collection = []
        panel._history = []
        panel._envs = []
        panel._env_cb = self._Items()
        panel._hist_list = self._Items()
        panel._refresh_collection_ui = lambda: None
        panel._data_path = lambda: path
        return panel

    def test_legacy_rest_secrets_migrate_before_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rest.json"
            path.write_text(
                '{"collection":[{"name":"request","auth_value":"auth",'
                '"oauth2_client_secret":"oauth","headers":{"X-Token":"header"}}],'
                '"history":[],"envs":[{"name":"dev","variables":{"API_TOKEN":"env"}}]}',
                encoding="utf-8",
            )
            passwords = {}
            keyring = types.SimpleNamespace(
                get_password=lambda service, key: passwords.get((service, key)),
                set_password=lambda service, key, value: passwords.__setitem__((service, key), value),
            )
            with mock.patch.dict(sys.modules, {"keyring": keyring}):
                panel = self._panel(path)
                panel._load_data()

            saved = path.read_text(encoding="utf-8")
            self.assertNotIn('"auth"', saved)
            self.assertNotIn('"oauth"', saved)
            self.assertNotIn('"header"', saved)
            self.assertNotIn('"env"', saved)
            self.assertEqual(panel._collection[0].auth_value, "auth")
            self.assertEqual(panel._collection[0].headers["X-Token"], "header")
            self.assertEqual(panel._envs[0].variables["API_TOKEN"], "env")
            self.assertTrue(passwords)

    def test_failed_rest_migration_keeps_legacy_file_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rest.json"
            legacy = '{"collection":[{"auth_value":"auth"}],"history":[],"envs":[]}'
            path.write_text(legacy, encoding="utf-8")
            panel = self._panel(path)
            with mock.patch("core.secrets.set_secret", side_effect=secret_store.SecretStorageUnavailable):
                panel._load_data()
            self.assertEqual(path.read_text(encoding="utf-8"), legacy)

    def test_declarations_are_constrained_and_secrets_are_redacted(self):
        self.assertEqual(
            _safe_pre_request_variables(
                '{"TOKEN": {"from": "response.json.access_token"}}',
                '{"access_token": "abc"}',
            ),
            {"TOKEN": "abc"},
        )
        with self.assertRaises(ValueError):
            _safe_pre_request_variables("__import__('os').system('false')", "{}")
        self.assertEqual(
            _safe_test_results('[{"name": "ok", "status": 200}]',
                               {"status": 200, "body": "", "elapsed": 0}),
            [("ok", True)],
        )

        request = HttpRequest()
        request.auth_value = "bearer-secret"
        request.oauth2_client_secret = "oauth-secret"
        request.headers = {"Authorization": "secret", "Accept": "application/json"}
        request.pre_script = "__import__('os').system('false')"
        request.post_tests = "__import__('os').system('false')"
        serialized = request.to_dict()
        self.assertEqual(serialized["auth_value"], "<redacted>")
        self.assertEqual(serialized["oauth2_client_secret"], "<redacted>")
        self.assertEqual(serialized["headers"]["Authorization"], "<redacted>")
        self.assertEqual(serialized["pre_script"], "")
        self.assertEqual(serialized["post_tests"], "")
        self.assertNotIn("bearer-secret", request.to_http_file_block())

        imported = HttpRequest.from_dict(serialized)
        self.assertEqual(imported.auth_value, "")
        self.assertEqual(imported.oauth2_client_secret, "")
        self.assertEqual(imported.headers, {"Accept": "application/json"})
        self.assertEqual(imported.pre_script, "")
        self.assertEqual(imported.post_tests, "")
        self.assertEqual(
            EnvProfile.from_dict({"name": "dev", "variables": {"API_TOKEN": "x", "host": "ok"}}).variables,
            {"host": "ok"},
        )

    def test_request_and_ai_workers_cancel_idempotently(self):
        worker = _AIWorker("ollama", "model", "", [])
        response = mock.Mock()
        worker._current_resp = response
        worker.stop()
        worker.stop()
        self.assertTrue(worker._stop_event.is_set())
        self.assertEqual(response.close.call_count, 2)


class SharedSecretConsumersTest(unittest.TestCase):
    def test_git_and_ai_use_shared_secret_helpers(self):
        with mock.patch("core.secrets.set_secret") as set_secret:
            _save_token("github", "token")
        set_secret.assert_called_once_with("git/github_token", "token")
        with mock.patch("core.secrets.get_secret", return_value="token") as get_secret:
            self.assertEqual(_AIPanel._get_key(object(), "openai"), "token")
        get_secret.assert_called_once_with("ai/openai_key")

    def test_ftp_profiles_never_serialize_passwords_and_worker_cancel_is_safe(self):
        profile = FtpProfile(password="secret")
        self.assertEqual(profile.to_dict()["password"], "")
        self.assertEqual(FtpProfile.from_dict({"password": "legacy"}).password, "")
        worker = _FtpOpWorker(lambda: "done")
        worker.cancel()
        worker.run()

    def test_ftp_legacy_json_and_keyring_credentials_migrate_before_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            path.write_text(
                '[{"name":"json","password":"json-secret"}, {"name":"old","password":""}]',
                encoding="utf-8",
            )
            passwords = {("NotePadPQ_FTP", "old"): "old-secret"}

            def get_password(service, key):
                return passwords.get((service, key))

            def set_password(service, key, value):
                passwords[(service, key)] = value

            def delete_password(service, key):
                passwords.pop((service, key), None)

            keyring = types.SimpleNamespace(
                get_password=get_password,
                set_password=set_password,
                delete_password=delete_password,
            )
            panel = _FtpPanel.__new__(_FtpPanel)
            panel._profiles = []
            panel._profiles_path = lambda: path
            with mock.patch.dict(sys.modules, {"keyring": keyring}):
                panel._load_profiles()

            self.assertEqual([profile.password for profile in panel._profiles], ["json-secret", "old-secret"])
            self.assertNotIn("json-secret", path.read_text(encoding="utf-8"))
            self.assertEqual(passwords[("NotePadPQ", "ftp/json/password")], "json-secret")
            self.assertEqual(passwords[("NotePadPQ", "ftp/old/password")], "old-secret")
            self.assertNotIn(("NotePadPQ_FTP", "old"), passwords)

    def test_failed_ftp_json_migration_keeps_plaintext_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            legacy = '[{"name":"legacy","password":"secret"}]'
            path.write_text(legacy, encoding="utf-8")
            panel = _FtpPanel.__new__(_FtpPanel)
            panel._profiles = []
            panel._profiles_path = lambda: path
            with mock.patch("core.secrets.set_secret", side_effect=secret_store.SecretStorageUnavailable):
                panel._load_profiles()
            self.assertEqual(path.read_text(encoding="utf-8"), legacy)

    def test_ftp_cancellation_closes_late_connection_and_resets_ui(self):
        class Button:
            def __init__(self):
                self.text = ""

            def setEnabled(self, _enabled):
                pass

            def setText(self, text):
                self.text = text

        class Status:
            def __init__(self):
                self.text = ""

            def set_busy(self, _busy, _cancellable=False):
                pass

            def setText(self, text):
                self.text = text

        connection = ("ftp", mock.Mock())
        panel = _FtpPanel.__new__(_FtpPanel)
        panel._btn_connect = Button()
        panel._tree = mock.Mock(setEnabled=lambda _enabled: None)
        panel._status = Status()
        panel._conn = None
        panel._cancel_requested = True
        panel._on_async_cancelled(None, connection)

        connection[1].close.assert_called_once_with()
        self.assertIsNone(panel._conn)
        self.assertTrue(panel._status.text)


class UserPluginTrustTest(unittest.TestCase):
    def _manager(self, root: Path) -> PluginManager:
        manager = PluginManager.__new__(PluginManager)
        manager._plugins = {}
        manager._main_window = object()
        manager._disabled_path = root / "disabled.json"
        manager._trusted_path = root / "trusted.json"
        manager._disabled = set()
        manager._trusted = set()
        manager._plugins_dir = lambda: root
        return manager

    @staticmethod
    def _plugin(path: Path, name: str, marker: Path = None) -> None:
        side_effect = ""
        if marker is not None:
            side_effect = f"Path({str(marker)!r}).write_text('imported')\n"
        path.write_text(
            "from pathlib import Path\n"
            "from plugins.base_plugin import BasePlugin\n"
            + side_effect
            + "class TestPlugin(BasePlugin):\n"
            + f"    NAME = {name!r}\n"
            + "    VERSION = '1'\n"
            + "    DESCRIPTION = ''\n"
            + "    AUTHOR = ''\n"
            + "    def on_load(self, main_window): pass\n",
            encoding="utf-8",
        )

    def test_user_plugin_requires_explicit_enable_and_duplicate_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "imported"
            first = root / "first.py"
            second = root / "second.py"
            self._plugin(first, "User plugin", marker)
            self._plugin(second, "User plugin")
            manager = self._manager(root)

            self.assertTrue(manager._load_plugin_file(first, manager._main_window))
            self.assertFalse(marker.exists())
            self.assertFalse(manager._plugins["User plugin"]["enabled"])
            self.assertTrue(manager.enable_plugin("User plugin"))
            self.assertTrue(marker.exists())
            self.assertFalse(manager._load_plugin_file(second, manager._main_window))

    def test_user_plugin_symlinks_and_changed_trusted_code_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.py"
            linked = root / "linked.py"
            self._plugin(target, "User plugin")
            linked.symlink_to(target)
            manager = self._manager(root)
            self.assertFalse(manager._load_plugin_file(linked, manager._main_window))

            self.assertTrue(manager._load_plugin_file(target, manager._main_window))
            self.assertTrue(manager.enable_plugin("User plugin"))
            self.assertEqual(manager._trusted["User plugin"]["path"], str(target.resolve()))
            target.write_text(target.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
            self.assertFalse(manager._is_trusted("User plugin", target))


if __name__ == "__main__":
    unittest.main()
