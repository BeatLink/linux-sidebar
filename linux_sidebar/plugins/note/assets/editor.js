/* The page side of the note plugin: it builds the CKEditor instance and talks to the sidebar.
   Everything crosses the boundary as a JSON message, so nothing here has to return a value. */

(function () {
    "use strict";

    var options = window.SIDEBAR_OPTIONS || {};
    var editor = null;
    var applying = false;
    /* Nothing counts as an edit until the sidebar has put the stored note in. */
    var armed = false;

    function post(message) {
        try {
            window.webkit.messageHandlers.sidebar.postMessage(JSON.stringify(message));
        } catch (error) {
            /* Running outside the sidebar, where there is nothing to talk to. */
        }
    }

    /* Builds the plugin list, which is what the format setting actually changes. */
    function pluginList(ck) {
        var wanted = [
            "Essentials", "Paragraph", "Heading", "Bold", "Italic", "Underline",
            "Strikethrough", "Code", "Subscript", "Superscript", "Link", "AutoLink",
            "List", "ListProperties", "TodoList", "BlockQuote", "CodeBlock",
            "HorizontalLine", "Table", "TableToolbar", "TableCaption", "Autoformat",
            "PasteFromOffice", "TextTransformation", "RemoveFormat", "Alignment",
            "Indent", "IndentBlock", "FindAndReplace", "SourceEditing", "WordCount",
            "Highlight", "SpecialCharacters", "SpecialCharactersEssentials"
        ];
        if (options.format === "markdown") {
            wanted.push("Markdown");
        } else {
            wanted.push("GeneralHtmlSupport", "FontColor", "FontBackgroundColor");
        }
        return wanted.map(function (name) { return ck[name]; }).filter(Boolean);
    }

    /* Builds the toolbar, which the toolbar setting trims down. */
    function toolbarItems() {
        if (options.toolbar === "compact") {
            return ["bold", "italic", "|", "bulletedList", "numberedList", "todoList",
                    "|", "link", "|", "undo", "redo"];
        }
        return [
            "undo", "redo", "|", "heading", "|", "bold", "italic", "underline",
            "strikethrough", "code", "removeFormat", "|", "bulletedList", "numberedList",
            "todoList", "outdent", "indent", "|", "link", "blockQuote", "codeBlock",
            "insertTable", "horizontalLine", "specialCharacters", "|", "alignment",
            "highlight", "|", "findAndReplace", "sourceEditing"
        ];
    }

    function configuration(ck) {
        var config = {
            licenseKey: "GPL",
            plugins: pluginList(ck),
            toolbar: { items: toolbarItems(), shouldNotGroupWhenFull: false },
            heading: {
                options: [
                    { model: "paragraph", title: "Paragraph", class: "ck-heading_paragraph" },
                    { model: "heading1", view: "h1", title: "Heading 1", class: "ck-heading_heading1" },
                    { model: "heading2", view: "h2", title: "Heading 2", class: "ck-heading_heading2" },
                    { model: "heading3", view: "h3", title: "Heading 3", class: "ck-heading_heading3" }
                ]
            },
            list: { properties: { styles: true, startIndex: true, reversed: false } },
            link: { addTargetToExternalLinks: false, defaultProtocol: "https://" },
            table: { contentToolbar: ["tableColumn", "tableRow", "mergeTableCells", "toggleTableCaption"] },
            placeholder: options.placeholder || ""
        };
        if (options.format !== "markdown") {
            config.htmlSupport = { allow: [{ name: /.*/, attributes: true, classes: true, styles: true }] };
        }
        return config;
    }

    /* Turns plain text into the paragraphs a tag-free note should become. */
    function textToHtml(text) {
        return text.split(/\n{2,}/).map(function (block) {
            var escaped = block
                .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
            return "<p>" + escaped.replace(/\n/g, "<br>") + "</p>";
        }).join("");
    }

    function wireWordCount() {
        var plugin = editor.plugins.has("WordCount") ? editor.plugins.get("WordCount") : null;
        if (!plugin) {
            return;
        }
        plugin.on("update", function (_event, stats) {
            post({ type: "count", words: stats.words, characters: stats.characters });
        });
    }

    function wireChanges() {
        editor.model.document.on("change:data", function () {
            if (armed && !applying) {
                post({ type: "change" });
            }
        });
    }

    /* The compositor may not offer a docked surface the clipboard, so the sidebar handles it. */
    function wireKeys() {
        var root = editor.editing.view.document;
        root.on("keydown", function (event, data) {
            var key = data.domEvent.key;
            var ctrl = data.domEvent.ctrlKey || data.domEvent.metaKey;
            if (key === "Escape") {
                post({ type: "escape" });
                data.preventDefault();
                event.stop();
                return;
            }
            if (!ctrl) {
                return;
            }
            if (key === "s" || key === "S") {
                post({ type: "save" });
            } else if (key === "c" || key === "C") {
                post({ type: "clipboard", action: "copy", text: selectionText() });
            } else if (key === "x" || key === "X") {
                post({ type: "clipboard", action: "cut", text: selectionText() });
                editor.model.deleteContent(editor.model.document.selection);
            } else if (key === "v" || key === "V") {
                post({ type: "paste" });
            } else {
                return;
            }
            data.preventDefault();
            event.stop();
        }, { priority: "highest" });
    }

    function selectionText() {
        var selection = window.getSelection();
        return selection ? selection.toString() : "";
    }

    /* A menu drawn in the page cannot be misplaced by the compositor the way a real one can. */
    function wireContextMenu() {
        var menu = document.createElement("div");
        menu.id = "context-menu";
        menu.style.cssText = "position:fixed;display:none;z-index:9999;min-width:140px;" +
            "background:var(--sidebar-base);color:var(--sidebar-fg);border-radius:6px;" +
            "border:1px solid var(--sidebar-border);padding:4px;box-shadow:0 2px 8px rgba(0,0,0,.3);";
        document.body.appendChild(menu);

        var actions = [
            ["Cut", function () {
                post({ type: "clipboard", action: "cut", text: selectionText() });
                editor.model.deleteContent(editor.model.document.selection);
            }, true],
            ["Copy", function () {
                post({ type: "clipboard", action: "copy", text: selectionText() });
            }, true],
            ["Paste", function () { post({ type: "paste" }); }, false],
            ["Select All", function () { editor.execute("selectAll"); }, false]
        ];

        actions.forEach(function (action) {
            var item = document.createElement("div");
            item.textContent = action[0];
            item.dataset.needsSelection = action[2] ? "yes" : "no";
            item.style.cssText = "padding:4px 10px;border-radius:4px;cursor:default;";
            item.addEventListener("mouseenter", function () {
                item.style.background = "var(--sidebar-hover)";
            });
            item.addEventListener("mouseleave", function () { item.style.background = ""; });
            item.addEventListener("mousedown", function (event) {
                event.preventDefault();
                menu.style.display = "none";
                action[1]();
                editor.editing.view.focus();
            });
            menu.appendChild(item);
        });

        document.addEventListener("contextmenu", function (event) {
            event.preventDefault();
            var has = selectionText().length > 0;
            Array.prototype.forEach.call(menu.children, function (item) {
                var needed = item.dataset.needsSelection === "yes";
                item.style.opacity = needed && !has ? "0.4" : "1";
                item.style.pointerEvents = needed && !has ? "none" : "auto";
            });
            menu.style.display = "block";
            menu.style.left = Math.min(event.clientX, window.innerWidth - menu.offsetWidth - 4) + "px";
            menu.style.top = Math.min(event.clientY, window.innerHeight - menu.offsetHeight - 4) + "px";
        });
        document.addEventListener("mousedown", function (event) {
            if (!menu.contains(event.target)) {
                menu.style.display = "none";
            }
        });
    }

    /* The bridge the sidebar calls into. */
    window.sidebarSetData = function (text, format) {
        if (!editor) {
            return;
        }
        applying = true;
        if (format !== "markdown" && text && text.indexOf("<") === -1) {
            text = textToHtml(text);
        }
        editor.setData(text || "");
        applying = false;
        armed = true;
    };

    window.sidebarGetData = function (requestId) {
        post({ type: "data", id: requestId, value: editor ? editor.getData() : "" });
    };

    window.sidebarInsert = function (text, mime) {
        if (!editor || !text) {
            return;
        }
        var html = mime === "text/html" ? text : textToHtml(text);
        var fragment = editor.data.processor.toView(html);
        editor.model.insertContent(editor.data.toModel(fragment));
        editor.editing.view.focus();
    };

    window.sidebarFocus = function () {
        if (editor) {
            editor.editing.view.focus();
        }
    };

    window.sidebarSetTheme = function (css) {
        var node = document.getElementById("sidebar-theme");
        if (!node) {
            node = document.createElement("style");
            node.id = "sidebar-theme";
            document.head.appendChild(node);
        }
        node.textContent = css;
    };

    window.sidebarSetToolbar = function (mode) {
        document.body.classList.toggle("toolbar-hidden", mode === "hidden");
    };

    function start() {
        var ck = window.CKEDITOR;
        if (!ck || !ck.DecoupledEditor) {
            post({ type: "error", message: "the CKEditor bundle did not load" });
            return;
        }
        ck.DecoupledEditor.create(document.getElementById("editor"), configuration(ck))
            .then(function (created) {
                editor = created;
                document.getElementById("toolbar").appendChild(editor.ui.view.toolbar.element);
                window.sidebarSetToolbar(options.toolbar);
                wireWordCount();
                wireChanges();
                wireKeys();
                wireContextMenu();
                post({ type: "ready" });
            })
            .catch(function (error) {
                post({ type: "error", message: String(error && error.message || error) });
            });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
}());
