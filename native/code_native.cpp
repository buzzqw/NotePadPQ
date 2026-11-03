// Fast syntax scanner for C-family languages (Go, Rust, Kotlin, Swift, Scala,
// Dart) used by NotePadPQ's PygmentsLexer.
//
// Pygments tokenises ~2-4 MB/s in Python and every token costs a Python call;
// this scanner styles the same text at well over 100 MB/s and hands Scintilla
// one style byte per input byte, applied with a single SCI_SETSTYLINGEX.
//
// It mirrors the colours Pygments produces rather than defining new ones: the
// keyword/type/builtin tables are generated from Pygments itself
// (native/generate_code_tables.py) and the style numbers are those of
// editor/pygments_lexer.py.  When the extension is not compiled the editor
// keeps using Pygments, so the module is purely an accelerator.
//
// Like the LaTeX scanner it has no Qt dependency, which keeps wheels and
// distro builds simple.

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cstddef>
#include <cstring>
#include <string_view>
#include <unordered_set>
#include <vector>

namespace {

// Must match editor/pygments_lexer.py.
constexpr unsigned char S_DEFAULT = 0;
constexpr unsigned char S_KEYWORD = 1;
constexpr unsigned char S_KWTYPE = 2;
constexpr unsigned char S_BUILTIN = 3;
constexpr unsigned char S_COMMENT = 4;
constexpr unsigned char S_DOCSTR = 5;
constexpr unsigned char S_STRING = 6;
constexpr unsigned char S_NUMBER = 7;
constexpr unsigned char S_OPERATOR = 8;
constexpr unsigned char S_FUNCTION = 9;
constexpr unsigned char S_CLASS = 10;
constexpr unsigned char S_DECORATOR = 11;
constexpr unsigned char S_NAMESPACE = 12;
constexpr unsigned char S_PREPROC = 13;

constexpr int MAX_NESTING = 32;

#include "code_lexer_tables.inc"

using WordSet = std::unordered_set<std::string_view>;

WordSet make_set(const char *const *words) {
    WordSet set;
    for (; *words; ++words) set.insert(*words);
    return set;
}

WordSet make_set(std::initializer_list<const char *> words) {
    WordSet set;
    for (const char *word : words) set.insert(word);
    return set;
}

enum class Interp : unsigned char { None, Dollar, Backslash };

// What follows a namespace keyword (package/import/mod).
enum class NsMode : unsigned char {
    None,
    Path,        // Kotlin: the whole dotted path is one namespace token
    Single,      // Rust `mod name`
    SingleClass, // Swift `import Foundation` (Pygments colours it as a class)
    Segments,    // Scala: lower-case segments until end of line
};

// Pending context set by the previous keyword.
enum Pending : int { P_NONE = 0, P_FUNCTION, P_CLASS, P_NS_PATH, P_NS_SINGLE, P_NS_CLASS, P_NS_SEGMENTS };

struct Lang {
    const char *name;
    WordSet keywords, types, builtins;
    WordSet function_decl;   // the next identifier is a function name
    WordSet class_decl;      // the next identifier is a type name
    WordSet namespace_decl;  // package/import/mod
    NsMode ns_mode;
    WordSet macros;          // Rust macros Pygments colours as functions
    const char *operators;   // single-byte operator characters
    bool colon_pairs;        // ':' is an operator only in "::" and ":="
    bool arrow_default;      // "->" is punctuation, not an operator
    bool nested_comments;
    bool multiline_strings;  // "..." may span lines (Rust)
    bool backtick_raw;       // Go `raw strings`
    bool triple_quotes;      // """...""" (and ''' in Dart)
    bool single_quote_strings;  // Dart '...'
    bool char_literals;      // 'x' (otherwise ' is an operator: lifetimes)
    bool rust_prefixes;      // r"..", r#".."#, b"..", br"..", b'x'
    bool rust_macros;        // known name! macros are functions
    bool doc_comments;       // Rust ///, //!, /** */ are docstrings
    bool amp_keyword;        // Rust: & is a keyword (Keyword.Pseudo)
    bool dollar_preproc;     // Rust macro_rules! $vars
    bool backtick_idents;    // Kotlin `quoted names`
    bool rust_typename;      // after `:` / `->` the next name is a type
    bool rust_attributes;    // #[...] / #![...] are preprocessor
    bool hash_directives;    // Swift #if/#endif/#selector...
    bool scala_prefixes;     // s"..", f"..", raw"..": interpolated strings
    bool capitalized_class;  // Scala colours every Capitalised name
    int at_style;            // style for @name, -1 if not special
    Interp interp;
};

std::vector<Lang> &languages() {
    static std::vector<Lang> langs = [] {
        std::vector<Lang> v;
        Lang go{};
        go.name = "go";
        go.keywords = make_set(GO_KEYWORDS);
        go.types = make_set(GO_TYPES);
        go.builtins = make_set(GO_BUILTINS);
        go.operators = "+-*/%=&|^!<>";
        go.colon_pairs = true;
        go.ns_mode = NsMode::None;
        go.backtick_raw = true;
        go.char_literals = true;
        go.at_style = -1;
        go.interp = Interp::None;
        go.ns_mode = NsMode::None;
        v.push_back(std::move(go));

        Lang rust{};
        rust.name = "rust";
        rust.keywords = make_set(RUST_KEYWORDS);
        rust.types = make_set(RUST_TYPES);
        rust.builtins = make_set(RUST_BUILTINS);
        rust.function_decl = make_set({"fn"});
        rust.class_decl = make_set({"struct", "enum", "union", "type"});
        rust.rust_typename = true;
        rust.namespace_decl = make_set({"mod"});
        rust.ns_mode = NsMode::Single;
        rust.macros = make_set(RUST_MACROS);
        rust.doc_comments = true;
        rust.amp_keyword = true;
        rust.dollar_preproc = true;
        rust.operators = "+-*/%=|^!<>~?@.";
        rust.arrow_default = true;
        rust.nested_comments = true;
        rust.multiline_strings = true;
        rust.char_literals = true;
        rust.rust_prefixes = true;
        rust.rust_macros = true;
        rust.rust_attributes = true;
        rust.at_style = -1;
        rust.interp = Interp::None;
        v.push_back(std::move(rust));

        Lang kotlin{};
        kotlin.name = "kotlin";
        kotlin.keywords = make_set(KOTLIN_KEYWORDS);
        kotlin.types = make_set(KOTLIN_TYPES);
        kotlin.builtins = make_set(KOTLIN_BUILTINS);
        kotlin.function_decl = make_set({"fun"});
        kotlin.class_decl = make_set({"class", "interface", "object"});
        kotlin.namespace_decl = make_set({"package", "import"});
        kotlin.ns_mode = NsMode::Path;
        kotlin.backtick_idents = true;
        kotlin.operators = "+-*/%=&|^!<>~?";
        kotlin.colon_pairs = true;
        kotlin.nested_comments = true;
        kotlin.triple_quotes = true;
        kotlin.char_literals = true;
        kotlin.at_style = S_DECORATOR;
        kotlin.interp = Interp::Dollar;
        v.push_back(std::move(kotlin));

        Lang swift{};
        swift.name = "swift";
        swift.keywords = make_set(SWIFT_KEYWORDS);
        swift.types = make_set(SWIFT_TYPES);
        swift.builtins = make_set(SWIFT_BUILTINS);
        swift.function_decl = make_set({"func"});
        swift.class_decl = make_set({"class", "struct", "enum", "protocol", "extension", "actor"});
        swift.namespace_decl = make_set({"import"});
        swift.ns_mode = NsMode::SingleClass;
        swift.keywords.insert("_");
        swift.operators = "+-*/%&|^!<>~";
        swift.arrow_default = true;
        swift.nested_comments = true;
        swift.triple_quotes = true;
        swift.hash_directives = true;
        swift.at_style = -1;
        swift.interp = Interp::Backslash;
        v.push_back(std::move(swift));

        Lang scala{};
        scala.name = "scala";
        scala.keywords = make_set(SCALA_KEYWORDS);
        scala.types = make_set(SCALA_TYPES);
        scala.builtins = make_set(SCALA_BUILTINS);
        scala.function_decl = make_set({"def"});
        scala.namespace_decl = make_set({"import"});
        scala.ns_mode = NsMode::Segments;
        scala.operators = "+-*/%=&|!<>~?";
        scala.colon_pairs = true;
        scala.nested_comments = true;
        scala.triple_quotes = true;
        scala.char_literals = true;
        scala.scala_prefixes = true;
        scala.capitalized_class = true;
        scala.at_style = S_DECORATOR;
        scala.interp = Interp::Dollar;
        v.push_back(std::move(scala));

        Lang dart{};
        dart.name = "dart";
        dart.keywords = make_set(DART_KEYWORDS);
        dart.types = make_set(DART_TYPES);
        dart.builtins = make_set(DART_BUILTINS);
        dart.class_decl = make_set({"class", "mixin"});
        dart.ns_mode = NsMode::None;
        dart.operators = "+-*/%=&|^!<>~?:";
        dart.nested_comments = true;
        dart.triple_quotes = true;
        dart.single_quote_strings = true;
        dart.at_style = S_DECORATOR;
        dart.interp = Interp::Dollar;
        v.push_back(std::move(dart));
        return v;
    }();
    return langs;
}

const Lang *find_lang(std::string_view name) {
    for (const Lang &lang : languages())
        if (name == lang.name) return &lang;
    return nullptr;
}

inline bool is_ident_start(unsigned char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_' || c >= 0x80;
}

inline bool is_ident_char(unsigned char c) {
    return is_ident_start(c) || (c >= '0' && c <= '9');
}

inline bool is_digit(unsigned char c) { return c >= '0' && c <= '9'; }

inline bool is_space(unsigned char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v';
}

class Scanner {
public:
    Scanner(const Lang &lang, const unsigned char *text, std::size_t len, std::size_t span)
        : lang_(lang), t_(text), n_(len), span_(span), styles_(len, S_DEFAULT) {}

    std::vector<unsigned char> &run() {
        std::size_t pos = 0;
        code(pos, 0, 0);
        return styles_;
    }

private:
    const Lang &lang_;
    const unsigned char *t_;
    std::size_t n_;
    std::size_t span_;
    std::vector<unsigned char> styles_;

    void paint(std::size_t a, std::size_t b, unsigned char style) {
        if (b > n_) b = n_;
        if (a < b) std::memset(styles_.data() + a, style, b - a);
    }

    bool at(std::size_t pos, const char *s) const {
        const std::size_t k = std::strlen(s);
        return pos + k <= n_ && std::memcmp(t_ + pos, s, k) == 0;
    }

    // Code until the closer of an interpolation (`}` or `)`) at depth 0, or
    // until the requested span is covered at top level.  Newlines inside an
    // interpolation keep the string style so that they are never mistaken
    // for a safe restart point by the Python side.
    void code(std::size_t &pos, unsigned char closer, int depth) {
        int nesting = 0;
        int pending_decl = 0;  // 1 = function name next, 2 = class name next
        while (pos < n_) {
            if (closer == 0 && pos >= span_) return;
            const unsigned char c = t_[pos];
            if (is_space(c)) {
                if (closer && c == '\n') styles_[pos] = S_STRING;
                if (c == '\n' && pending_decl == P_NS_SEGMENTS) pending_decl = P_NONE;
                ++pos;
                continue;
            }
            if (closer) {
                if (c == '(' || c == '{' || c == '[') ++nesting;
                else if ((c == ')' || c == '}' || c == ']') && nesting > 0) --nesting;
                else if (c == closer) return;
            }
            if (c == '/' && pos + 1 < n_ && t_[pos + 1] == '/') {
                const void *nl = std::memchr(t_ + pos, '\n', n_ - pos);
                const std::size_t end = nl ? static_cast<const unsigned char *>(nl) - t_ : n_;
                const bool doc = lang_.doc_comments && pos + 2 < n_ &&
                                 ((t_[pos + 2] == '/' && !(pos + 3 < n_ && t_[pos + 3] == '/')) ||
                                  t_[pos + 2] == '!');
                paint(pos, end, doc ? S_DOCSTR : S_COMMENT);
                pos = end;
                continue;
            }
            if (c == '/' && pos + 1 < n_ && t_[pos + 1] == '*') {
                block_comment(pos);
                continue;
            }
            if (is_ident_start(c)) {
                identifier(pos, pending_decl, depth);
                continue;
            }
            if (c == '`' && lang_.backtick_idents) {
                const void *end = pos + 1 < n_ ? std::memchr(t_ + pos + 1, '`', n_ - pos - 1) : nullptr;
                const void *nl = pos + 1 < n_ ? std::memchr(t_ + pos + 1, '\n', n_ - pos - 1) : nullptr;
                if (end && (!nl || end < nl)) {
                    const std::size_t stop = static_cast<const unsigned char *>(end) - t_ + 1;
                    paint(pos, stop, pending_decl == P_FUNCTION ? S_FUNCTION : S_DEFAULT);
                    pending_decl = P_NONE;
                    pos = stop;
                    continue;
                }
            }
            // Scala imports: `a.b._` are namespaces, names inside `{...}` are not.
            if (pending_decl == P_NS_SEGMENTS && std::strchr("._*", c)) {
                ++pos;
                continue;
            }
            // Rust type position: `&` and lifetimes do not end it.
            if (lang_.rust_typename && pending_decl == P_CLASS && (c == '&' || c == '\'')) {
                if (c == '&') styles_[pos++] = S_KEYWORD;
                else quote(pos, depth);
                continue;
            }
            pending_decl = P_NONE;
            if (c == '$' && lang_.dollar_preproc && pos + 1 < n_ && is_ident_start(t_[pos + 1])) {
                std::size_t end = pos + 1;
                while (end < n_ && is_ident_char(t_[end])) ++end;
                paint(pos, end, S_PREPROC);
                pos = end;
                continue;
            }
            if (c == '&' && lang_.amp_keyword) {
                styles_[pos++] = S_KEYWORD;
                continue;
            }
            if (is_digit(c) || (c == '.' && pos + 1 < n_ && is_digit(t_[pos + 1]) &&
                                (pos == 0 || (t_[pos - 1] != '.' && !is_ident_char(t_[pos - 1]) &&
                                              t_[pos - 1] != ')' && t_[pos - 1] != ']')))) {
                number(pos);
                continue;
            }
            if (c == '"') {
                string(pos, depth, lang_.interp, false);
                continue;
            }
            if (c == '\'') {
                quote(pos, depth);
                continue;
            }
            if (c == '`' && lang_.backtick_raw) {
                const void *end = pos + 1 < n_ ? std::memchr(t_ + pos + 1, '`', n_ - pos - 1) : nullptr;
                const std::size_t stop = end ? static_cast<const unsigned char *>(end) - t_ + 1 : n_;
                paint(pos, stop, S_STRING);
                pos = stop;
                continue;
            }
            if (c == '@' && lang_.at_style >= 0 && pos + 1 < n_ && is_ident_start(t_[pos + 1])) {
                std::size_t end = pos + 1;
                while (end < n_ && (is_ident_char(t_[end]) || t_[end] == '.')) ++end;
                paint(pos, end, static_cast<unsigned char>(lang_.at_style));
                pos = end;
                continue;
            }
            if (c == '#' && lang_.rust_attributes &&
                (at(pos, "#[") || at(pos, "#!["))) {
                attribute(pos);
                continue;
            }
            if (c == '#' && lang_.hash_directives && pos + 1 < n_ && is_ident_start(t_[pos + 1])) {
                std::size_t end = pos + 1;
                while (end < n_ && is_ident_char(t_[end])) ++end;
                const std::string_view word(reinterpret_cast<const char *>(t_ + pos), end - pos);
                if (word == "#if" || word == "#elseif" || word == "#else" || word == "#endif" ||
                    word == "#warning" || word == "#error") {
                    const void *nl = std::memchr(t_ + pos, '\n', n_ - pos);
                    end = nl ? static_cast<const unsigned char *>(nl) - t_ : n_;
                }
                paint(pos, end, S_PREPROC);
                pos = end;
                continue;
            }
            operator_or_punctuation(pos, pending_decl);
        }
    }

    void block_comment(std::size_t &pos) {
        const std::size_t start = pos;
        const bool doc = lang_.doc_comments && pos + 2 < n_ &&
                         ((t_[pos + 2] == '*' && !(pos + 3 < n_ && t_[pos + 3] == '/' )) || t_[pos + 2] == '!');
        int level = 1;
        pos += 2;
        while (pos < n_ && level > 0) {
            if (t_[pos] == '*' && pos + 1 < n_ && t_[pos + 1] == '/') {
                --level;
                pos += 2;
            } else if (lang_.nested_comments && t_[pos] == '/' && pos + 1 < n_ && t_[pos + 1] == '*') {
                ++level;
                pos += 2;
            } else {
                ++pos;
            }
        }
        paint(start, pos, doc ? S_DOCSTR : S_COMMENT);
    }

    void identifier(std::size_t &pos, int &pending_decl, int depth) {
        const std::size_t start = pos;
        if (pending_decl == P_NS_PATH) {
            while (pos < n_ && (is_ident_char(t_[pos]) || t_[pos] == '.' || t_[pos] == '*')) ++pos;
            paint(start, pos, S_NAMESPACE);
            pending_decl = P_NONE;
            return;
        }
        while (pos < n_ && is_ident_char(t_[pos])) ++pos;
        const std::string_view word(reinterpret_cast<const char *>(t_ + start), pos - start);
        if (pending_decl == P_NS_SINGLE || pending_decl == P_NS_CLASS) {
            paint(start, pos, pending_decl == P_NS_SINGLE ? S_NAMESPACE : S_CLASS);
            pending_decl = P_NONE;
            return;
        }
        if (pending_decl == P_NS_SEGMENTS) {
            const bool upper = t_[start] >= 'A' && t_[start] <= 'Z';
            paint(start, pos, upper ? S_CLASS : S_NAMESPACE);
            return;  // stays pending until the end of the line
        }

        if (lang_.rust_prefixes && pos < n_ && (word == "r" || word == "b" || word == "br")) {
            if (t_[pos] == '"' || (t_[pos] == '#' && word != "b")) {
                if (rust_raw_or_byte_string(start, pos)) { pending_decl = 0; return; }
            } else if (word == "b" && t_[pos] == '\'') {
                pos = start + 1;
                quote(pos, depth);
                paint(start, start + 1, S_STRING);
                pending_decl = 0;
                return;
            }
        }
        if (lang_.scala_prefixes && pos < n_ && t_[pos] == '"') {
            paint(start, pos, S_STRING);
            string(pos, depth, Interp::Dollar, false);
            pending_decl = 0;
            return;
        }
        if (lang_.single_quote_strings && word == "r" && pos < n_ && (t_[pos] == '"' || t_[pos] == '\'')) {
            paint(start, pos, S_STRING);
            string(pos, depth, Interp::None, true);
            pending_decl = 0;
            return;
        }
        if (lang_.rust_macros && pos < n_ && t_[pos] == '!' &&
            !(pos + 1 < n_ && t_[pos + 1] == '=') && lang_.macros.count(word)) {
            paint(start, pos + 1, S_FUNCTION);
            ++pos;
            pending_decl = 0;
            return;
        }

        // Kotlin extension functions: `fun Receiver.name(`.
        if (pending_decl == P_FUNCTION && lang_.backtick_idents && pos < n_ && t_[pos] == '.') {
            paint(start, pos, S_DEFAULT);
            ++pos;
            return;
        }
        if (pending_decl == P_CLASS && lang_.rust_typename &&
            (lang_.types.count(word) || lang_.builtins.count(word))) {
            // Pygments keeps builtin types (Vec, u8...) as they are and
            // stays in the type position.
            paint(start, pos, lang_.types.count(word) ? S_KWTYPE : S_BUILTIN);
            return;
        }
        unsigned char style = S_DEFAULT;
        if (pending_decl == P_FUNCTION) style = S_FUNCTION;
        else if (pending_decl == P_CLASS) style = S_CLASS;
        else if (lang_.keywords.count(word)) style = S_KEYWORD;
        else if (lang_.types.count(word)) style = S_KWTYPE;
        else if (lang_.builtins.count(word)) style = S_BUILTIN;
        else if (lang_.capitalized_class && t_[start] >= 'A' && t_[start] <= 'Z') style = S_CLASS;
        paint(start, pos, style);

        if (pending_decl) pending_decl = P_NONE;
        else if (lang_.function_decl.count(word)) pending_decl = P_FUNCTION;
        else if (lang_.class_decl.count(word)) pending_decl = P_CLASS;
        else if (lang_.namespace_decl.count(word)) {
            switch (lang_.ns_mode) {
            case NsMode::Path: pending_decl = P_NS_PATH; break;
            case NsMode::Single: pending_decl = P_NS_SINGLE; break;
            case NsMode::SingleClass: pending_decl = P_NS_CLASS; break;
            case NsMode::Segments: pending_decl = P_NS_SEGMENTS; break;
            case NsMode::None: break;
            }
        }
    }

    bool rust_raw_or_byte_string(std::size_t start, std::size_t &pos) {
        std::size_t p = pos;
        const bool raw = t_[start] == 'r' || (pos - start == 2);
        if (!raw) {  // b"..."
            string(p, 0, Interp::None, false);
            paint(start, pos, S_STRING);
            pos = p;
            return true;
        }
        std::size_t hashes = 0;
        while (p < n_ && t_[p] == '#') { ++hashes; ++p; }
        if (p >= n_ || t_[p] != '"') return false;
        ++p;
        while (p < n_) {
            if (t_[p] == '"') {
                std::size_t k = 0;
                while (k < hashes && p + 1 + k < n_ && t_[p + 1 + k] == '#') ++k;
                if (k == hashes) { p += 1 + hashes; break; }
            }
            ++p;
        }
        paint(start, p, S_STRING);
        pos = p;
        return true;
    }

    void number(std::size_t &pos) {
        const std::size_t start = pos;
        if (t_[pos] == '0' && pos + 1 < n_ &&
            (t_[pos + 1] == 'x' || t_[pos + 1] == 'X' || t_[pos + 1] == 'b' ||
             t_[pos + 1] == 'B' || t_[pos + 1] == 'o' || t_[pos + 1] == 'O')) {
            pos += 2;
            while (pos < n_ && (is_ident_char(t_[pos]))) ++pos;
            paint(start, pos, S_NUMBER);
            return;
        }
        while (pos < n_) {
            const unsigned char c = t_[pos];
            if (is_digit(c) || c == '_') { ++pos; continue; }
            if (c == '.' && pos + 1 < n_ && is_digit(t_[pos + 1])) { ++pos; continue; }
            if ((c == 'e' || c == 'E') && pos + 1 < n_ &&
                (is_digit(t_[pos + 1]) ||
                 ((t_[pos + 1] == '+' || t_[pos + 1] == '-') && pos + 2 < n_ && is_digit(t_[pos + 2])))) {
                pos += 2;
                continue;
            }
            break;
        }
        while (pos < n_ && is_ident_char(t_[pos]) && t_[pos] < 0x80) ++pos;  // suffix: u32, f64, L
        paint(start, pos, S_NUMBER);
    }

    // `pos` is on the opening quote.  Handles "..." and, when enabled,
    // """...""" / '''...''' plus interpolation.
    void string(std::size_t &pos, int depth, Interp interp, bool raw) {
        const unsigned char q = t_[pos];
        const bool triple = lang_.triple_quotes && pos + 2 < n_ && t_[pos + 1] == q && t_[pos + 2] == q;
        const bool multiline = triple || lang_.multiline_strings;
        std::size_t seg = pos;
        pos += triple ? 3 : 1;
        while (pos < n_) {
            const unsigned char c = t_[pos];
            if (c == '\\' && !raw) {
                if (interp == Interp::Backslash && pos + 1 < n_ && t_[pos + 1] == '(' && depth < MAX_NESTING) {
                    paint(seg, pos + 2, S_STRING);
                    pos += 2;
                    code(pos, ')', depth + 1);
                    seg = pos;  // the closing ')' belongs to the string
                    if (pos < n_) ++pos;
                    continue;
                }
                pos += pos + 1 < n_ ? 2 : 1;
                continue;
            }
            if (c == '$' && interp == Interp::Dollar && !raw && pos + 1 < n_) {
                if (t_[pos + 1] == '{' && depth < MAX_NESTING) {
                    paint(seg, pos + 2, S_STRING);
                    pos += 2;
                    code(pos, '}', depth + 1);
                    seg = pos;
                    if (pos < n_) ++pos;
                    continue;
                }
                if (is_ident_start(t_[pos + 1])) {
                    paint(seg, pos + 1, S_STRING);
                    std::size_t end = pos + 1;
                    while (end < n_ && is_ident_char(t_[end])) ++end;
                    pos = end;
                    seg = pos;
                    continue;
                }
            }
            if (c == q) {
                if (!triple) { ++pos; break; }
                if (pos + 2 < n_ && t_[pos + 1] == q && t_[pos + 2] == q) {
                    pos += 3;
                    while (pos < n_ && t_[pos] == q) ++pos;  // Kotlin: """"x""""
                    break;
                }
            }
            if (c == '\n' && !multiline) break;
            ++pos;
        }
        paint(seg, pos, S_STRING);
    }

    void quote(std::size_t &pos, int depth) {
        if (lang_.single_quote_strings) {
            string(pos, depth, lang_.interp, false);
            return;
        }
        if (lang_.char_literals) {
            std::size_t p = pos + 1;
            if (p < n_ && t_[p] == '\\') {
                p += 2;
                while (p < n_ && t_[p] != '\'' && t_[p] != '\n' && p - pos < 16) ++p;
            } else if (p < n_ && t_[p] != '\'' && t_[p] != '\n') {
                ++p;
                while (p < n_ && (t_[p] & 0xC0) == 0x80) ++p;  // rest of a UTF-8 char
            }
            if (p < n_ && t_[p] == '\'') {
                paint(pos, p + 1, S_STRING);
                pos = p + 1;
                return;
            }
        }
        paint(pos, pos + 1, S_OPERATOR);  // Rust lifetimes, Scala symbols
        ++pos;
        if (lang_.rust_macros && at(pos, "static") && !(pos + 6 < n_ && is_ident_char(t_[pos + 6]))) {
            paint(pos, pos + 6, S_BUILTIN);
            pos += 6;
        }
    }

    // #[...] / #![...]: preprocessor, except string literals inside it.
    void attribute(std::size_t &pos) {
        std::size_t segment = pos;
        int level = 0;
        while (pos < n_) {
            const unsigned char c = t_[pos];
            if (c == '"') {
                paint(segment, pos, S_PREPROC);
                string(pos, 0, Interp::None, false);
                segment = pos;
                continue;
            }
            if (c == '[') ++level;
            else if (c == ']' && --level == 0) { ++pos; break; }
            else if (c == '\n') break;
            ++pos;
        }
        paint(segment, pos, S_PREPROC);
    }

    void operator_or_punctuation(std::size_t &pos, int &pending_decl) {
        const unsigned char c = t_[pos];
        if (lang_.rust_typename && c == ':') {
            if (pos + 1 < n_ && t_[pos + 1] == ':') { pos += 2; return; }
            pending_decl = P_CLASS;
            ++pos;
            return;
        }
        if (c == ':' && lang_.colon_pairs) {
            if (pos + 1 < n_ && (t_[pos + 1] == ':' || t_[pos + 1] == '=' ||
                                 (t_[pos + 1] != 0 && std::strchr(lang_.operators, t_[pos + 1]) &&
                                  t_[pos + 1] != '.'))) {
                paint(pos, pos + 2, S_OPERATOR);
                pos += 2;
            } else {
                ++pos;
            }
            return;
        }
        if (c == '-' && lang_.arrow_default && pos + 1 < n_ && t_[pos + 1] == '>') {
            if (lang_.rust_typename) pending_decl = P_CLASS;
            pos += 2;
            return;
        }
        if (c == '.' && pos + 1 < n_ && t_[pos + 1] == '.' && std::strchr(lang_.operators, '.') == nullptr) {
            ++pos;
            return;
        }
        if (c != 0 && std::strchr(lang_.operators, c) != nullptr) {
            if (c == '.' && !(pos + 1 < n_ && t_[pos + 1] == '.') && !(pos > 0 && t_[pos - 1] == '.')) {
                ++pos;  // member access is punctuation
                return;
            }
            styles_[pos] = S_OPERATOR;
        }
        ++pos;
    }
};

PyObject *native_style(PyObject *, PyObject *args) {
    const char *lang_name = nullptr;
    Py_buffer view{};
    Py_ssize_t span_arg = 0;
    if (!PyArg_ParseTuple(args, "sy*n", &lang_name, &view, &span_arg)) return nullptr;
    const Lang *lang = find_lang(lang_name);
    if (!lang) {
        PyBuffer_Release(&view);
        PyErr_Format(PyExc_ValueError, "unsupported language: %s", lang_name);
        return nullptr;
    }
    const auto *text = static_cast<const unsigned char *>(view.buf);
    const std::size_t len = static_cast<std::size_t>(view.len);
    std::size_t span = span_arg < 0 ? len : static_cast<std::size_t>(span_arg);
    if (span > len) span = len;

    // The scan only touches the pinned buffer and C++ memory, so other
    // Python threads (checker, autocomplete, LSP) keep running meanwhile.
    std::vector<unsigned char> styles;
    Py_BEGIN_ALLOW_THREADS
    Scanner scanner(*lang, text, len, span);
    styles = std::move(scanner.run());
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&view);
    return PyBytes_FromStringAndSize(reinterpret_cast<const char *>(styles.data()),
                                     static_cast<Py_ssize_t>(span));
}

PyObject *native_languages(PyObject *, PyObject *) {
    PyObject *names = PyTuple_New(static_cast<Py_ssize_t>(languages().size()));
    if (!names) return nullptr;
    Py_ssize_t i = 0;
    for (const Lang &lang : languages()) {
        PyObject *name = PyUnicode_FromString(lang.name);
        if (!name) { Py_DECREF(names); return nullptr; }
        PyTuple_SET_ITEM(names, i++, name);
    }
    return names;
}

PyMethodDef METHODS[] = {
    {"style", native_style, METH_VARARGS,
     "style(language, text, span) -> bytes: one style byte for each of the first span bytes."},
    {"languages", native_languages, METH_NOARGS, "Languages supported by the scanner."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef MODULE = {
    PyModuleDef_HEAD_INIT,
    "core._code_native",
    "Native C-family syntax scanner used by NotePadPQ.",
    -1,
    METHODS,
};

}  // namespace

PyMODINIT_FUNC PyInit__code_native() {
    return PyModule_Create(&MODULE);
}
