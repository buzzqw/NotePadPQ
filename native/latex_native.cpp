// Fast LaTeX syntax scanner for NotePadPQ.
//
// This module deliberately has no Qt/QScintilla dependency.  It is a small
// CPython extension used by the existing QsciLexerCustom wrapper.  Keeping the
// scanner independent makes wheels and distro builds considerably less brittle
// than exposing a second SIP QScintilla type.

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
#include <cstddef>
#include <cstring>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

namespace {

enum class Mode : unsigned char {
    Default,
    Dollar,
    DoubleDollar,
    Paren,
    Bracket,
    Environment,
    Verbatim,
};

struct State {
    Mode mode = Mode::Default;
    std::vector<std::string> environments;
};

struct Command {
    std::size_t end;
    std::string name;
};

constexpr unsigned char B_PERCENT = '%';
constexpr unsigned char B_BACKSLASH = '\\';
constexpr unsigned char B_DOLLAR = '$';
constexpr unsigned char B_LBRACE = '{';
constexpr unsigned char B_RBRACE = '}';
constexpr unsigned char B_LBRACKET = '[';
constexpr unsigned char B_RBRACKET = ']';
constexpr unsigned char B_NEWLINE = '\n';

constexpr unsigned char S_DEFAULT = 0;
constexpr unsigned char S_COMMAND = 1;
constexpr unsigned char S_STRUCTURE = 2;
constexpr unsigned char S_REFERENCE = 3;
constexpr unsigned char S_COMMENT = 4;
constexpr unsigned char S_MATH = 5;
constexpr unsigned char S_BRACE = 6;
constexpr unsigned char S_OPTION = 7;
constexpr unsigned char S_REF_ARG = 8;
constexpr std::size_t NATIVE_MAX_STYLE_BYTES = 256 * 1024;

// Command/environment classification comes from core/latex_commands.py (the
// single source of truth shared with the Python lexer).  Regenerate the include
// with `python native/generate_command_tables.py` after editing that module;
// tests/test_latex_commands.py fails when it is stale.
#include "latex_command_tables.inc"

bool is_command_first(unsigned char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '@';
}

bool is_command_continue(unsigned char c) {
    return is_command_first(c) || c == '*';
}

bool is_escaped(const unsigned char *text, std::size_t pos) {
    std::size_t count = 0;
    while (pos > 0 && text[pos - 1] == B_BACKSLASH) {
        --pos;
        ++count;
    }
    return (count & 1U) != 0;
}

bool parse_command(const unsigned char *text, std::size_t length,
                   std::size_t pos, Command &out) {
    std::size_t i = pos + 1;
    if (i >= length || !is_command_first(text[i])) {
        return false;
    }
    const std::size_t begin = i++;
    while (i < length && is_command_continue(text[i])) {
        ++i;
    }
    out.end = i;
    out.name.assign(reinterpret_cast<const char *>(text + begin), i - begin);
    return true;
}

bool environment_token(const unsigned char *text, std::size_t length,
                       std::size_t pos, const Command *command,
                       bool verbatim, std::size_t &after, bool &is_begin,
                       std::string &name) {
    Command local;
    if (!command) {
        if (!parse_command(text, length, pos, local)) {
            return false;
        }
        command = &local;
    }
    if (command->name != "begin" && command->name != "end") {
        return false;
    }
    const std::size_t brace = command->end;
    if (brace >= length || text[brace] != B_LBRACE) {
        return false;
    }
    const unsigned char *close_ptr = static_cast<const unsigned char *>(
        std::memchr(text + brace + 1, B_RBRACE, length - brace - 1));
    if (!close_ptr) {
        return false;
    }
    const std::size_t close = static_cast<std::size_t>(close_ptr - text);
    name.assign(reinterpret_cast<const char *>(text + brace + 1), close - brace - 1);
    std::string lookup = name;
    if (!verbatim) {
        while (!lookup.empty() && lookup.back() == '*') {
            lookup.pop_back();
        }
        if (MATH_ENVIRONMENTS.find(lookup) == MATH_ENVIRONMENTS.end()) {
            return false;
        }
        name = std::move(lookup);
    } else if (VERBATIM_ENVIRONMENTS.find(lookup) == VERBATIM_ENVIRONMENTS.end()) {
        return false;
    }
    after = close + 1;
    is_begin = command->name == "begin";
    return true;
}

std::size_t verb_inline_end(const unsigned char *text, std::size_t length,
                            std::size_t pos, const Command &command) {
    std::size_t i = pos + (command.name == "verb*" ? 6 : 5);
    if (i >= length) {
        return 0;
    }
    const unsigned char delimiter = text[i];
    if (delimiter == B_BACKSLASH || delimiter == ' ' ||
        (delimiter < 128 && ((delimiter >= 'a' && delimiter <= 'z') ||
                             (delimiter >= 'A' && delimiter <= 'Z')))) {
        return 0;
    }
    const unsigned char *newline = static_cast<const unsigned char *>(
        std::memchr(text + i + 1, B_NEWLINE, length - i - 1));
    const std::size_t limit = newline ? static_cast<std::size_t>(newline - text) : length;
    const unsigned char *close = static_cast<const unsigned char *>(
        std::memchr(text + i + 1, delimiter, limit - i - 1));
    return close ? static_cast<std::size_t>(close - text) + 1 : limit;
}

bool math_environment(const unsigned char *text, std::size_t length,
                      std::size_t pos, const Command *command,
                      std::size_t &after, bool &is_begin, std::string &name) {
    return environment_token(text, length, pos, command, false, after, is_begin, name);
}

void paint(std::vector<unsigned char> &styles, std::size_t safe,
           std::size_t pos, std::size_t stop, unsigned char style) {
    const std::size_t lo = std::max(pos, safe) - safe;
    const std::size_t hi = std::min(stop, safe + styles.size()) - safe;
    if (hi > lo) {
        std::fill(styles.begin() + static_cast<std::ptrdiff_t>(lo),
                  styles.begin() + static_cast<std::ptrdiff_t>(hi), style);
    }
}

PyObject *mode_to_python(Mode mode) {
    switch (mode) {
    case Mode::Dollar: return PyUnicode_FromString("dollar");
    case Mode::DoubleDollar: return PyUnicode_FromString("double");
    case Mode::Paren: return PyUnicode_FromString("paren");
    case Mode::Bracket: return PyUnicode_FromString("bracket");
    case Mode::Environment: return PyUnicode_FromString("environment");
    case Mode::Verbatim: return PyUnicode_FromString("verbatim");
    default: return PyUnicode_FromString("default");
    }
}

bool mode_from_python(PyObject *value, Mode &mode) {
    if (!PyUnicode_Check(value)) {
        return false;
    }
    const char *name = PyUnicode_AsUTF8(value);
    if (!name) {
        return false;
    }
    if (std::strcmp(name, "dollar") == 0) mode = Mode::Dollar;
    else if (std::strcmp(name, "double") == 0) mode = Mode::DoubleDollar;
    else if (std::strcmp(name, "paren") == 0) mode = Mode::Paren;
    else if (std::strcmp(name, "bracket") == 0) mode = Mode::Bracket;
    else if (std::strcmp(name, "environment") == 0) mode = Mode::Environment;
    else if (std::strcmp(name, "verbatim") == 0) mode = Mode::Verbatim;
    else mode = Mode::Default;
    return true;
}

bool envs_from_python(PyObject *value, std::vector<std::string> &envs) {
    if (!PyTuple_Check(value) && !PyList_Check(value)) {
        return false;
    }
    const Py_ssize_t size = PySequence_Size(value);
    if (size < 0) return false;
    envs.clear();
    envs.reserve(static_cast<std::size_t>(size));
    for (Py_ssize_t i = 0; i < size; ++i) {
        PyObject *item = PySequence_GetItem(value, i);
        if (!item) return false;
        if (!PyUnicode_Check(item)) {
            Py_DECREF(item);
            return false;
        }
        const char *name = PyUnicode_AsUTF8(item);
        if (!name) {
            Py_DECREF(item);
            return false;
        }
        envs.emplace_back(name);
        Py_DECREF(item);
    }
    return true;
}

PyObject *envs_to_python(const std::vector<std::string> &envs) {
    PyObject *tuple = PyTuple_New(static_cast<Py_ssize_t>(envs.size()));
    if (!tuple) return nullptr;
    for (std::size_t i = 0; i < envs.size(); ++i) {
        PyObject *item = PyUnicode_FromStringAndSize(
            envs[i].data(), static_cast<Py_ssize_t>(envs[i].size()));
        if (!item) {
            Py_DECREF(tuple);
            return nullptr;
        }
        PyTuple_SET_ITEM(tuple, static_cast<Py_ssize_t>(i), item);
    }
    return tuple;
}

PyObject *native_style(PyObject *, PyObject *args) {
    Py_buffer view{};
    Py_ssize_t start_arg = 0;
    Py_ssize_t end_arg = 0;
    PyObject *mode_obj = nullptr;
    PyObject *envs_obj = nullptr;
    if (!PyArg_ParseTuple(args, "y*nnOO", &view, &start_arg, &end_arg,
                          &mode_obj, &envs_obj)) {
        return nullptr;
    }

    const auto *text = static_cast<const unsigned char *>(view.buf);
    const std::size_t length = static_cast<std::size_t>(view.len);
    std::size_t requested_start = start_arg < 0 ? 0 : static_cast<std::size_t>(start_arg);
    std::size_t requested_end = end_arg < 0 ? 0 : static_cast<std::size_t>(end_arg);
    requested_start = std::min(requested_start, length);
    requested_end = std::min(std::max(requested_end, requested_start), length);

    Mode mode;
    std::vector<std::string> envs;
    if (!mode_from_python(mode_obj, mode) || !envs_from_python(envs_obj, envs)) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_TypeError, "invalid LaTeX scanner state");
        return nullptr;
    }

    // QScintilla always asks from a line boundary, but keeping this guard here
    // makes the C API safe for direct tests and future callers.
    std::size_t safe = requested_start;
    while (safe > 0 && text[safe - 1] != B_NEWLINE) {
        --safe;
    }
    const std::size_t hard_end = std::min(
        requested_end, std::min(length, safe + NATIVE_MAX_STYLE_BYTES));
    if (safe >= hard_end) {
        PyBuffer_Release(&view);
        PyObject *empty = PyBytes_FromStringAndSize(nullptr, 0);
        PyObject *checkpoints = PyList_New(0);
        PyObject *result = PyTuple_New(3);
        if (!empty || !checkpoints || !result) {
            Py_XDECREF(empty); Py_XDECREF(checkpoints); Py_XDECREF(result);
            return nullptr;
        }
        PyTuple_SET_ITEM(result, 0, PyLong_FromSize_t(safe));
        PyTuple_SET_ITEM(result, 1, empty);
        PyTuple_SET_ITEM(result, 2, checkpoints);
        return result;
    }

    std::vector<unsigned char> styles(hard_end - safe, S_DEFAULT);
    PyObject *checkpoint_list = PyList_New(0);
    if (!checkpoint_list) {
        PyBuffer_Release(&view);
        return nullptr;
    }

    auto cache_checkpoint = [&](std::size_t position) -> bool {
        PyObject *entry = PyTuple_New(3);
        if (!entry) return false;
        PyTuple_SET_ITEM(entry, 0, PyLong_FromSize_t(position));
        PyTuple_SET_ITEM(entry, 1, mode_to_python(mode));
        PyObject *py_envs = envs_to_python(envs);
        if (!py_envs) {
            Py_DECREF(entry);
            return false;
        }
        PyTuple_SET_ITEM(entry, 2, py_envs);
        if (PyList_Append(checkpoint_list, entry) < 0) {
            Py_DECREF(entry);
            return false;
        }
        Py_DECREF(entry);
        return true;
    };

    std::size_t pos = safe;
    std::string last_command;
    while (pos < hard_end) {
        const unsigned char b = text[pos];
        if (b == B_NEWLINE) {
            if (!cache_checkpoint(pos + 1)) goto error;
            ++pos;
            last_command.clear();
            continue;
        }

        if (b == B_PERCENT && mode != Mode::Verbatim && !is_escaped(text, pos)) {
            const unsigned char *newline = static_cast<const unsigned char *>(
                std::memchr(text + pos, B_NEWLINE, hard_end - pos));
            const std::size_t stop = newline ? static_cast<std::size_t>(newline - text) : hard_end;
            paint(styles, safe, pos, stop, S_COMMENT);
            pos = stop;
            continue;
        }

        if (mode == Mode::Default) {
            if (b == B_DOLLAR && !is_escaped(text, pos)) {
                const std::size_t width = (pos + 1 < length && text[pos + 1] == B_DOLLAR) ? 2 : 1;
                paint(styles, safe, pos, pos + width, S_MATH);
                mode = width == 2 ? Mode::DoubleDollar : Mode::Dollar;
                pos += width;
                continue;
            }
            if (pos + 1 < length && text[pos] == B_BACKSLASH &&
                (text[pos + 1] == '(' || text[pos + 1] == '[')) {
                paint(styles, safe, pos, pos + 2, S_MATH);
                mode = text[pos + 1] == '(' ? Mode::Paren : Mode::Bracket;
                pos += 2;
                continue;
            }
            if (b == B_BACKSLASH) {
                Command command;
                const bool has_command = parse_command(text, length, pos, command);
                std::size_t after = 0;
                bool is_begin = false;
                std::string environment;
                if (has_command && math_environment(text, length, pos, &command,
                                                     after, is_begin, environment) && is_begin) {
                    paint(styles, safe, pos, after, S_MATH);
                    mode = Mode::Environment;
                    envs.push_back(std::move(environment));
                    pos = after;
                    continue;
                }
                environment.clear();
                if (has_command && environment_token(text, length, pos, &command, true,
                                                      after, is_begin, environment) && is_begin) {
                    paint(styles, safe, pos, after, S_STRUCTURE);
                    mode = Mode::Verbatim;
                    envs.push_back(std::move(environment));
                    pos = after;
                    continue;
                }
                if (has_command && (command.name == "verb" || command.name == "verb*")) {
                    const std::size_t verb_end = verb_inline_end(text, length, pos, command);
                    if (verb_end) {
                        paint(styles, safe, pos, verb_end, S_COMMAND);
                        pos = verb_end;
                        last_command.clear();
                        continue;
                    }
                }
                if (has_command) {
                    const unsigned char style = STRUCTURE_COMMANDS.find(command.name) != STRUCTURE_COMMANDS.end()
                        ? S_STRUCTURE
                        : (REFERENCE_COMMANDS.find(command.name) != REFERENCE_COMMANDS.end()
                           ? S_REFERENCE : S_COMMAND);
                    paint(styles, safe, pos, command.end, style);
                    pos = command.end;
                    last_command = command.name;
                    continue;
                }
                paint(styles, safe, pos, std::min(pos + 2, length), S_COMMAND);
                pos += (pos + 1 < length) ? 2 : 1;
                last_command.clear();
                continue;
            }
            if (b == B_LBRACE) {
                paint(styles, safe, pos, pos + 1, S_BRACE);
                ++pos;
                if (REFERENCE_COMMANDS.find(last_command) != REFERENCE_COMMANDS.end()) {
                    std::size_t i = pos;
                    int depth = 1;
                    while (i < length && depth) {
                        if (text[i] == B_BACKSLASH && i + 1 < length) {
                            i += 2;
                            continue;
                        }
                        if (text[i] == B_LBRACE) ++depth;
                        else if (text[i] == B_RBRACE) --depth;
                        ++i;
                    }
                    const std::size_t content_end = depth == 0 ? i - 1 : i;
                    paint(styles, safe, pos, content_end, S_REF_ARG);
                    pos = std::min(content_end, hard_end);
                }
                last_command.clear();
                continue;
            }
            if (b == B_LBRACKET) {
                paint(styles, safe, pos, pos + 1, S_BRACE);
                const unsigned char *close_ptr = static_cast<const unsigned char *>(
                    std::memchr(text + pos + 1, B_RBRACKET, length - pos - 1));
                const unsigned char *newline_ptr = static_cast<const unsigned char *>(
                    std::memchr(text + pos + 1, B_NEWLINE, length - pos - 1));
                const std::size_t close = close_ptr ? static_cast<std::size_t>(close_ptr - text) : length;
                const std::size_t newline = newline_ptr ? static_cast<std::size_t>(newline_ptr - text) : length;
                if (close < newline) {
                    paint(styles, safe, pos + 1, close, S_OPTION);
                    pos = std::min(close, hard_end);
                } else {
                    ++pos;
                }
                continue;
            }
            if (b == B_RBRACE || b == B_RBRACKET) {
                paint(styles, safe, pos, pos + 1, S_BRACE);
                ++pos;
                continue;
            }
            const unsigned char *special = nullptr;
            for (std::size_t i = pos; i < hard_end; ++i) {
                if (text[i] == B_PERCENT || text[i] == B_BACKSLASH || text[i] == B_DOLLAR ||
                    text[i] == B_LBRACE || text[i] == B_RBRACE || text[i] == B_LBRACKET ||
                    text[i] == B_RBRACKET || text[i] == B_NEWLINE) {
                    special = text + i;
                    break;
                }
            }
            const std::size_t stop = special ? static_cast<std::size_t>(special - text) : hard_end;
            if (stop > pos) {
                pos = stop;
                last_command.clear();
            } else {
                ++pos;
                last_command.clear();
            }
            continue;
        }

        if (mode == Mode::Environment && b == B_BACKSLASH) {
            Command command;
            const bool has_command = parse_command(text, length, pos, command);
            std::size_t after = 0;
            bool is_begin = false;
            std::string environment;
            if (has_command && math_environment(text, length, pos, &command,
                                                 after, is_begin, environment)) {
                paint(styles, safe, pos, after, S_MATH);
                if (is_begin) {
                    envs.push_back(std::move(environment));
                } else if (!envs.empty() && envs.back() == environment) {
                    envs.pop_back();
                    if (envs.empty()) mode = Mode::Default;
                }
                pos = after;
                continue;
            }
        }

        if (mode == Mode::Verbatim) {
            const unsigned char *newline = static_cast<const unsigned char *>(
                std::memchr(text + pos, B_NEWLINE, hard_end - pos));
            const unsigned char *backslash = static_cast<const unsigned char *>(
                std::memchr(text + pos, B_BACKSLASH, hard_end - pos));
            std::size_t stop = hard_end;
            if (newline) stop = std::min(stop, static_cast<std::size_t>(newline - text));
            if (backslash) stop = std::min(stop, static_cast<std::size_t>(backslash - text));
            if (stop > pos) {
                pos = stop;
                continue;
            }
            Command command;
            const bool has_command = parse_command(text, length, pos, command);
            std::size_t after = 0;
            bool is_begin = false;
            std::string environment;
            if (has_command && environment_token(text, length, pos, &command, true,
                                                  after, is_begin, environment) && !is_begin &&
                !envs.empty() && envs.back() == environment) {
                paint(styles, safe, pos, after, S_STRUCTURE);
                envs.pop_back();
                if (envs.empty()) mode = Mode::Default;
                pos = after;
            } else {
                ++pos;
            }
            continue;
        }

        const bool closing =
            (mode == Mode::Dollar && b == B_DOLLAR && !is_escaped(text, pos)) ||
            (mode == Mode::DoubleDollar && pos + 1 < length && text[pos] == B_DOLLAR &&
             text[pos + 1] == B_DOLLAR && !is_escaped(text, pos)) ||
            (mode == Mode::Paren && pos + 1 < length && text[pos] == B_BACKSLASH &&
             text[pos + 1] == ')' && !is_escaped(text, pos)) ||
            (mode == Mode::Bracket && pos + 1 < length && text[pos] == B_BACKSLASH &&
             text[pos + 1] == ']' && !is_escaped(text, pos));
        if (closing) {
            const std::size_t width = mode == Mode::DoubleDollar || mode == Mode::Paren || mode == Mode::Bracket ? 2 : 1;
            paint(styles, safe, pos, pos + width, S_MATH);
            mode = Mode::Default;
            pos += width;
            continue;
        }
        const unsigned char *special = nullptr;
        for (std::size_t i = pos; i < hard_end; ++i) {
            if (text[i] == B_NEWLINE || text[i] == B_DOLLAR || text[i] == B_BACKSLASH) {
                special = text + i;
                break;
            }
        }
        const std::size_t stop = special ? static_cast<std::size_t>(special - text) : hard_end;
        if (stop > pos) {
            paint(styles, safe, pos, stop, S_MATH);
            pos = stop;
        } else {
            paint(styles, safe, pos, pos + 1, S_MATH);
            ++pos;
        }
    }

    {
        PyObject *style_bytes = PyBytes_FromStringAndSize(
            reinterpret_cast<const char *>(styles.data()), static_cast<Py_ssize_t>(styles.size()));
        if (!style_bytes) goto error;
        PyBuffer_Release(&view);
        PyObject *result = PyTuple_New(3);
        if (!result) {
            Py_DECREF(style_bytes);
            Py_DECREF(checkpoint_list);
            return nullptr;
        }
        PyTuple_SET_ITEM(result, 0, PyLong_FromSize_t(safe));
        PyTuple_SET_ITEM(result, 1, style_bytes);
        PyTuple_SET_ITEM(result, 2, checkpoint_list);
        return result;
    }

error:
    PyBuffer_Release(&view);
    Py_XDECREF(checkpoint_list);
    return nullptr;
}

PyObject *native_state(PyObject *, PyObject *args) {
    Py_buffer view{};
    Py_ssize_t start_arg = 0;
    Py_ssize_t end_arg = 0;
    PyObject *mode_obj = nullptr;
    PyObject *envs_obj = nullptr;
    if (!PyArg_ParseTuple(args, "y*nnOO", &view, &start_arg, &end_arg,
                          &mode_obj, &envs_obj)) {
        return nullptr;
    }
    const auto *text = static_cast<const unsigned char *>(view.buf);
    const std::size_t length = static_cast<std::size_t>(view.len);
    std::size_t start = std::min<std::size_t>(std::max<Py_ssize_t>(start_arg, 0), length);
    const std::size_t end = std::min<std::size_t>(std::max<Py_ssize_t>(end_arg, 0), length);
    Mode mode;
    std::vector<std::string> envs;
    if (!mode_from_python(mode_obj, mode) || !envs_from_python(envs_obj, envs)) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_TypeError, "invalid LaTeX scanner state");
        return nullptr;
    }

    // The state-only path shares the same transitions as styling but avoids
    // allocating a style buffer.  A small implementation here is preferable
    // to asking the Python lexer to rescan a multi-megabyte prefix on a random
    // viewport request.
    std::size_t pos = start;
    while (pos < end) {
        if (text[pos] == B_NEWLINE) { ++pos; continue; }
        if (text[pos] == B_PERCENT && mode != Mode::Verbatim && !is_escaped(text, pos)) {
            const unsigned char *nl = static_cast<const unsigned char *>(std::memchr(text + pos, B_NEWLINE, end - pos));
            pos = nl ? static_cast<std::size_t>(nl - text) : end;
            continue;
        }
        const unsigned char b = text[pos];
        if (mode == Mode::Default) {
            if (b == B_DOLLAR && !is_escaped(text, pos)) {
                const std::size_t width = pos + 1 < length && text[pos + 1] == B_DOLLAR ? 2 : 1;
                mode = width == 2 ? Mode::DoubleDollar : Mode::Dollar; pos += width; continue;
            }
            if (pos + 1 < length && b == B_BACKSLASH && (text[pos + 1] == '(' || text[pos + 1] == '[')) {
                mode = text[pos + 1] == '(' ? Mode::Paren : Mode::Bracket; pos += 2; continue;
            }
            if (b == B_BACKSLASH) {
                Command command; const bool has = parse_command(text, length, pos, command);
                std::size_t after; bool begin; std::string name;
                if (has && math_environment(text, length, pos, &command, after, begin, name) && begin) {
                    mode = Mode::Environment; envs.push_back(std::move(name)); pos = after; continue;
                }
                name.clear();
                if (has && environment_token(text, length, pos, &command, true, after, begin, name) && begin) {
                    mode = Mode::Verbatim; envs.push_back(std::move(name)); pos = after; continue;
                }
                if (has && (command.name == "verb" || command.name == "verb*")) {
                    const std::size_t e = verb_inline_end(text, length, pos, command);
                    if (e) { pos = e; continue; }
                }
                pos = has ? command.end : std::min(pos + 2, length); continue;
            }
            ++pos; continue;
        }
        if (mode == Mode::Environment && b == B_BACKSLASH) {
            Command command; const bool has = parse_command(text, length, pos, command);
            std::size_t after; bool begin; std::string name;
            if (has && math_environment(text, length, pos, &command, after, begin, name)) {
                if (begin) envs.push_back(std::move(name));
                else if (!envs.empty() && envs.back() == name) { envs.pop_back(); if (envs.empty()) mode = Mode::Default; }
                pos = after; continue;
            }
        }
        if (mode == Mode::Verbatim) {
            const unsigned char *nl = static_cast<const unsigned char *>(std::memchr(text + pos, B_NEWLINE, end - pos));
            const unsigned char *bs = static_cast<const unsigned char *>(std::memchr(text + pos, B_BACKSLASH, end - pos));
            std::size_t stop = end;
            if (nl) stop = std::min(stop, static_cast<std::size_t>(nl - text));
            if (bs) stop = std::min(stop, static_cast<std::size_t>(bs - text));
            if (stop > pos) { pos = stop; continue; }
            Command command; const bool has = parse_command(text, length, pos, command);
            std::size_t after; bool begin; std::string name;
            if (has && environment_token(text, length, pos, &command, true, after, begin, name) &&
                !begin && !envs.empty() && envs.back() == name) {
                envs.pop_back(); if (envs.empty()) mode = Mode::Default; pos = after;
            } else ++pos;
            continue;
        }
        const bool closing =
            (mode == Mode::Dollar && b == B_DOLLAR && !is_escaped(text, pos)) ||
            (mode == Mode::DoubleDollar && pos + 1 < length && b == B_DOLLAR && text[pos + 1] == B_DOLLAR && !is_escaped(text, pos)) ||
            (mode == Mode::Paren && pos + 1 < length && b == B_BACKSLASH && text[pos + 1] == ')' && !is_escaped(text, pos)) ||
            (mode == Mode::Bracket && pos + 1 < length && b == B_BACKSLASH && text[pos + 1] == ']' && !is_escaped(text, pos));
        if (closing) { pos += mode == Mode::Dollar ? 1 : 2; mode = Mode::Default; continue; }
        ++pos;
    }

    PyObject *result = PyTuple_New(2);
    if (!result) { PyBuffer_Release(&view); return nullptr; }
    PyTuple_SET_ITEM(result, 0, mode_to_python(mode));
    PyTuple_SET_ITEM(result, 1, envs_to_python(envs));
    PyBuffer_Release(&view);
    return result;
}

PyMethodDef METHODS[] = {
    {"style", native_style, METH_VARARGS, "Style one bounded UTF-8 LaTeX chunk."},
    {"state", native_state, METH_VARARGS, "Compute LaTeX state over a byte range."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef MODULE = {
    PyModuleDef_HEAD_INIT,
    "core._latex_native",
    "Native LaTeX scanner used by NotePadPQ.",
    -1,
    METHODS,
};

} // namespace

PyMODINIT_FUNC PyInit__latex_native() {
    return PyModule_Create(&MODULE);
}
