// ─────────────────────────────────────────────
// Глобальные функции (вне IIFE, non-strict)
// ─────────────────────────────────────────────

function EditorSetupResizer(codeEl, resizer, sizeEl) {
    if (!codeEl || !codeEl.length) return;

    const el = codeEl[0];

    if (el.tagName === 'TEXTAREA') {
        let initialized = false;
        const ro = new ResizeObserver(() => {
            if (!initialized) { initialized = true; return; }
            if (sizeEl && typeof sizeEl.val === 'function') {
                sizeEl.val(String(el.offsetHeight));
            }
        });
        ro.observe(el);
        return;
    }

    // Monaco — drag-to-resize handle
    let $resizer;
    if (resizer) {
        $resizer = codeEl.find(resizer);
        if (!$resizer.length) return;
    } else {
        $resizer = codeEl.find('.monaco-resize-handle');
        if (!$resizer.length) {
            $resizer = $('<div class="monaco-resize-handle"></div>').css({
                height: '6px', cursor: 'ns-resize', width: '100%'
            });
            codeEl.after($resizer);
        }
    }

    const state = { active: false, startY: 0, startH: 0, lastY: 0, raf: 0, scrollY: 0, body: null };

    function applyResize() {
        state.raf = 0;
        if (!state.active) return;
        const newH = Math.max(20, state.startH + (state.lastY - state.startY));
        el.style.height = `${newH}px`;
    }

    function onMouseMove(e) {
        if (!state.active) return;
        state.lastY = e.clientY;
        if (!state.raf) state.raf = requestAnimationFrame(applyResize);
    }

    function onMouseUp() {
        if (!state.active) return;
        state.active = false;
        if (state.raf) { cancelAnimationFrame(state.raf); state.raf = 0; }
        $(document).off('.monacoResize');

        const b = state.body;
        document.body.style.position  = b.position;
        document.body.style.top       = b.top;
        document.body.style.left      = b.left;
        document.body.style.right     = b.right;
        document.body.style.userSelect = b.userSelect;
        window.scrollTo(0, state.scrollY);

        if (sizeEl && typeof sizeEl.val === 'function') {
            sizeEl.val(String(el.offsetHeight));
        }
    }

    function onMouseDown(e) {
        e.preventDefault();
        state.active  = true;
        state.startH  = el.getBoundingClientRect().height || el.scrollHeight;
        state.startY  = state.lastY = e.clientY;
        state.scrollY = window.scrollY || window.pageYOffset;
        state.body    = {
            position:   document.body.style.position,
            top:        document.body.style.top,
            left:       document.body.style.left,
            right:      document.body.style.right,
            userSelect: document.body.style.userSelect
        };
        document.body.style.position   = 'fixed';
        document.body.style.top        = `${-state.scrollY}px`;
        document.body.style.left       = '0';
        document.body.style.right      = '0';
        document.body.style.userSelect = 'none';
        $(document)
            .on('mousemove.monacoResize', onMouseMove)
            .on('mouseup.monacoResize', onMouseUp);
    }

    $resizer.off('mousedown.monacoResize').on('mousedown.monacoResize', onMouseDown);
}

function EditorRestoreSize(codeEl, sizeEl, defSize) {
    const height = String(sizeEl.val() || '');
    codeEl.css('height', height.length >= 2 ? `${height}px` : (defSize || '100px'));
}

function MonacoEditorInsertAtEnd(editor, text) {
    const model = editor.getModel();
    const old   = model.getValue();
    editor.executeEdits('format-json', [{
        range: model.getFullModelRange(),
        text: old.length > 0 ? `${old.trim()},\n${text}` : text
    }]);
    const lastLine = model.getLineCount();
    const pos = { lineNumber: lastLine, column: model.getLineMaxColumn(lastLine) };
    editor.pushUndoStop();
    editor.setPosition(pos);
    editor.revealPosition(pos);
}


// ─────────────────────────────────────────────
// Основная логика (IIFE, non-strict)
// ─────────────────────────────────────────────

(function (global) {

    // ── Утилиты ──────────────────────────────

    const _scriptPromises = {};

    function loadScript(url) {
        if (!_scriptPromises[url]) {
            _scriptPromises[url] = new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = url;
                script.onload = resolve;
                script.onerror = reject;
                document.head.appendChild(script);
            });
        }
        return _scriptPromises[url];
    }

    const _templateCache = {};

    global.loadTemplateSync = function (url, data) {
        if (!_templateCache[url]) {
            const xhr = new XMLHttpRequest();
            xhr.open('GET', url, false);
            xhr.send(null);
            if (xhr.status >= 200 && xhr.status < 300) {
                _templateCache[url] = _.template(xhr.responseText);
            } else {
                throw new Error('Cannot load template ' + url);
            }
        }
        return _templateCache[url](data || {});
    };


    // ── Реестр редакторов + авто-dispose ─────

    const _editorRegistry = [];

    function registerEditor(editor) {
        const node = editor.getDomNode();
        if (node) _editorRegistry.push({ editor, node });
    }

    function disposeEditorForNode(node) {
        const idx = _editorRegistry.findIndex(e => e.node === node);
        if (idx === -1) return;
        const { editor } = _editorRegistry[idx];
        const model = editor.getModel();
        editor.dispose();
        if (model) model.dispose();
        _editorRegistry.splice(idx, 1);
    }

    new MutationObserver(mutations => {
        mutations.forEach(m => {
            m.removedNodes.forEach(n => {
                if (!(n instanceof HTMLElement)) return;
                disposeEditorForNode(n);
                n.querySelectorAll('.monaco-editor').forEach(disposeEditorForNode);
            });
        });
    }).observe(document.body, { childList: true, subtree: true });

    global._isEditorInstalled = global.isEditorInstalled;
    global.isEditorInstalled = function () {
        const count = (global._isEditorInstalled ? global._isEditorInstalled() : 0) + _editorRegistry.length;
        console.log('editors count: ' + count);
        return count > 0;
    };


    // ── Форматирование (beautifier) ───────────

    const BEAUTIFIER_URL = 'https://beautifier.io/js/lib/beautifier.min.js';

    function basCodeSafe(text, restore) {
        if (!restore) {
            return text
                .replace(/\*\*\*([\s\S]*?)\*\*\*/g, (_, c) => `COOODE_${utf8_to_b64(c)}_COOODE`)
                .replace(/\[\[([\w.]+)\]\]/g,        (_, v) => `VAAAR_${v}_VAAAR`)
                .replace(/\{\{([\w.]+)\}\}/g,        (_, v) => `REEES_${v}_REEES`);
        }
        return text
            .replace(/COOODE_(.*?)_COOODE/g,  (_, c) => `***${b64_to_utf8(c)}***`)
            .replace(/VAAAR_([\w.]+)_VAAAR/g, (_, v) => `[[${v}]]`)
            .replace(/REEES_([\w.]+)_REEES/g, (_, v) => `{{${v}}}`);
    }

    function isLikelyXml(s) {
        s = String(s).trim();
        return s.indexOf('<') === 0;
    }

    function isLikelyJson(s) {
        s = String(s).trim();
        if (!s) return false;
        const first = s[0], last = s[s.length - 1];
        return (first === '{' && last === '}') || (first === '[' && last === ']');
    }

    function pretty(s, isJs) {
        const safe = basCodeSafe(s);
        if (isLikelyJson(safe) || isJs) {
            const code = basCodeSafe(beautifier.js(safe), true);
            return isJs
                ? code.replace(
                    /("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)|(\)\s+!)/g,
                    (match, str) => str ? match : ')!'
                  )
                : code;
        }
        if (isLikelyXml(safe)) return basCodeSafe(beautifier.html(safe), true);
        return String(s);
    }

    function formatCurrentEditor(editor, isJavascript) {
        const value = editor.getValue();
        loadScript(BEAUTIFIER_URL)
            .then(() => {
                require(['beautifier'], function (beautifier) {
                    window.beautifier = beautifier;
                    editor.setValue(pretty(value, isJavascript));
                }, err => prompt('beautifier require:', err));
            })
            .catch(err => prompt('beautifier:', err));
    }


    // ── Monaco: языки и токенайзеры ───────────

    let _monacoInitialized = false;

    const BASE_LANG_CONFIG = {
        brackets: [['{', '}'], ['[', ']'], ['(', ')']],
        autoClosingPairs: [
            { open: '(', close: ')' }, { open: '"', close: '"' },
            { open: "'", close: "'" }, { open: '`', close: '`' }
        ],
        surroundingPairs: [
            { open: '(', close: ')' }, { open: '"', close: '"' },
            { open: "'", close: "'" }, { open: '`', close: '`' }
        ],
        autoCloseBefore: 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    };

    const COMMON_INLINE_RULES = [
        [/\[\[\s*GLOBAL\s*:\w+/, { token: 'gvar', next: '@gvarTail' }],
        [/\[\[(?!\s*GLOBAL\s*:)\w+/, { token: 'var', next: '@varTail' }],
        [/\bVAR_\w+\b/, 'var'],
        [/\{\{[\w.]+\}\}/, 'res']
    ];

    const TAIL_SHARED = [
        ...COMMON_INLINE_RULES,
        [/"/, { token: 'string', next: '@dstring' }],
        [/'/, { token: 'string', next: '@sstring' }],
        [/[^\]"'\[]+/, 'jsBody'],
        [/\[(?!\[)/, 'jsBody'],
        [/\](?!\])/, 'jsBody']
    ];

    const STRING_SHARED = [
        ...COMMON_INLINE_RULES,
        [/\*\*\*/, { token: 'jsToken', next: '@js' }],
        [/\\./, 'string.escape']
    ];

    function buildBaseTokenizer() {
        return {
            tokenizer: {
                root: [
                    ...COMMON_INLINE_RULES,
                    [/\*\*\*/, { token: 'jsToken', next: '@js' }],
                    [/"/, { token: 'string', next: '@dstring' }],
                    [/'/, { token: 'string', next: '@sstring' }]
                ],
                gvarTail: [[/\]\]/, { token: 'gvar', next: '@pop' }], ...TAIL_SHARED],
                varTail:  [[/\]\]/, { token: 'var',  next: '@pop' }], ...TAIL_SHARED],
                js: [
                    ...COMMON_INLINE_RULES,
                    [/"/, { token: 'string', next: '@dstring' }],
                    [/'/, { token: 'string', next: '@sstring' }],
                    [/\*\*\*/, { token: 'jsToken', next: '@pop' }],
                    [/./, 'jsBody']
                ],
                dstring: [...STRING_SHARED, [/"/, { token: 'string', next: '@pop' }], [/./, 'string']],
                sstring: [...STRING_SHARED, [/'/, { token: 'string', next: '@pop' }], [/./, 'string']]
            }
        };
    }

    const PRIMITIVE_RULES = [
        [/\b(true|false|null)\b/, 'keyword'],
        [/-?\d+(\.\d+)?([eE][+-]?\d+)?/, 'number']
    ];

    const COMMENT_RULES = [
        [/\/\/.*$/, 'comment'],
        [/\/\*/, { token: 'comment.block', next: '@blockComment' }]
    ];

    const BLOCK_COMMENT_RULES = [
        [/[^/*]+/, 'comment.block'],
        [/\*\//, { token: 'comment.block', next: '@pop' }],
        [/[/*]/, 'comment.block']
    ];

    function initMonacoLanguages() {
        if (_monacoInitialized) return;
        _monacoInitialized = true;

        ['textEditor', 'textEditorGrammar', 'codeEditor'].forEach(id => {
            monaco.languages.register({ id });
            monaco.languages.setLanguageConfiguration(id, BASE_LANG_CONFIG);
        });

        const base = buildBaseTokenizer();

        monaco.languages.setMonarchTokensProvider('textEditor', base);

        monaco.languages.setMonarchTokensProvider('textEditorGrammar', {
            tokenizer: Object.assign({}, base.tokenizer, {
                root: [...base.tokenizer.root, ...PRIMITIVE_RULES]
            })
        });

        monaco.languages.setMonarchTokensProvider('codeEditor', {
            tokenizer: Object.assign({}, base.tokenizer, {
                root: [...COMMENT_RULES, ...base.tokenizer.root, ...PRIMITIVE_RULES],
                blockComment: BLOCK_COMMENT_RULES
            })
        });

        monaco.editor.defineTheme('textEditorTheme', {
            base: 'vs',
            inherit: true,
            rules: [
                { token: 'gvar',    foreground: '007acc', fontStyle: 'bold' },
                { token: 'var',     foreground: 'c71585', fontStyle: 'bold' },
                { token: 'res',     foreground: '03c03c', fontStyle: 'bold' },
                { token: 'func',    foreground: '6c2de1' },
                { token: 'jsToken', foreground: 'ff0000', fontStyle: 'bold' },
                { token: 'jsBody',  foreground: 'aa00ff' }
            ]
        });

        monaco.languages.typescript.javascriptDefaults.setCompilerOptions({
            allowNonTsExtensions: true,
            allowJs: false,
            checkJs: false,
            target: monaco.languages.typescript.ScriptTarget.ES5
        });

        const completionProvider = createVariableCompletionProvider();
        monaco.languages.registerCompletionItemProvider('textEditor',        completionProvider);
        monaco.languages.registerCompletionItemProvider('textEditorGrammar', completionProvider);
        monaco.languages.registerCompletionItemProvider('javascript',        completionProvider);
    }


    // ── TypeScript-подсказки для переменных BAS ──

    let _variableHistory = [];

    global.trackVariableUsage = function (varName) {
        const idx = _variableHistory.indexOf(varName);
        if (idx !== -1) _variableHistory.splice(idx, 1);
        _variableHistory.unshift(varName);
    };

    function dslPathToJsExpr(varName, path) {
        let expr = varName.replace(':', '');
        if (!path) return expr;
        path = path
            .replace(/\.at\((\d+)\)/g,               (_, i) => `[${parseInt(i, 10)}]`)
            .replace(/\.val\("((?:\\.|[^"\\])*)"\)/g, (_, k) => `[${JSON.stringify(k.replace(/\\"/g, '"'))}]`);
        return expr + path;
    }

    function escapeTsKey(key) {
        return JSON.stringify(String(key).replace(/:/g, '').replace('\\', '\\\\'));
    }

    function jsPrimitiveToTs(v) {
        if (v === null || v === undefined) return 'any';
        switch (typeof v) {
            case 'string':  return 'string';
            case 'number':  return 'number';
            case 'boolean': return 'boolean';
            default:        return null;
        }
    }

    function mergeTypes(types) {
        const uniq = types.filter((t, i, a) => t && a.indexOf(t) === i);
        return uniq.length ? uniq.join(', ') : 'any';
    }

    function jsValueToTsType(value) {
        if (value === null || value === undefined) return 'any';
        if (Array.isArray(value)) {
            return value.length ? `[${mergeTypes(value.map(jsValueToTsType))}]` : 'any[]';
        }
        const prim = jsPrimitiveToTs(value);
        if (prim) return prim;
        if (typeof value === 'object') {
            const props = Object.entries(value)
                .map(([k, v]) => `${escapeTsKey(k)}: ${jsValueToTsType(v)}`)
                .join('; ');
            return `{ ${props} }`;
        }
        return 'any';
    }

    function buildVarsDTS(vars) {
        const body = Object.entries(vars).map(([k, v]) => `${escapeTsKey(k)}: ${jsValueToTsType(v)}`);
        return `declare const vars: {\n${body.join(';\n')}\n};`;
    }

    function buildInsertTextFromDetail(label, details) {
        if (!details || !details.displayParts) return label;
        const parts = details.displayParts;
        let i = 0;
        while (i < parts.length && !(parts[i].kind === 'methodName' && parts[i].text === label)) i++;
        if (i >= parts.length) return label;
        while (i < parts.length && parts[i].text !== '(') i++;
        if (i >= parts.length) return label;
        i++;
        const args = [];
        while (i < parts.length && parts[i].text !== ')') {
            if (parts[i].kind === 'parameterName') args.push(parts[i].text);
            i++;
        }
        if (!args.length) return `${label}()`;
        if (args[0] === 'callbackfn' || args[0] === 'compareFn') {
            return `${label}(function(${args.slice(1).join(', ')}) {  })`;
        }
        return `${label}(${args.join(', ')})`;
    }

    async function getTsSuggestionsByExpr(jsExpr, vars) {
        const dts   = buildVarsDTS(vars);
        const code  = `${dts}\n\nvars.${jsExpr}`;
        const model = monaco.editor.createModel(code, 'javascript');
        try {
            const workerGetter = await monaco.languages.typescript.getJavaScriptWorker();
            const worker       = await workerGetter(model.uri);
            const result       = await worker.getCompletionsAtPosition(model.uri.toString(), code.length);
            if (!result || !result.entries) return [];

            return await Promise.all(
                result.entries
                    .filter(e => e.kind === 'method' || e.kind === 'function')
                    .map(async entry => {
                        const details    = await worker.getCompletionEntryDetails(model.uri.toString(), code.length, entry.name);
                        const detailText = details && details.displayParts ? details.displayParts.map(p => p.text).join('') : '';
                        const docText    = details && details.documentation ? details.documentation.map(p => p.text).join('') : '';
                        return {
                            label:         entry.name,
                            kind:          monaco.languages.CompletionItemKind.Method,
                            insertText:    buildInsertTextFromDetail(entry.name, details),
                            sortText:      entry.sortText || entry.name,
                            filterText:    entry.name,
                            detail:        detailText,
                            documentation: docText
                        };
                    })
            );
        } finally {
            model.dispose();
        }
    }

    function createVariableCompletionProvider() {
        return {
            triggerCharacters: ['.', '[', '{'],

            async provideCompletionItems(model, position) {
                const textBefore = model.getLineContent(position.lineNumber).substring(0, position.column - 1);

                // {{ → ресурсы
                if (textBefore.endsWith('{{')) {
                    const resources = _GobalModel.get('resources') || {};
                    return Object.keys(resources).map(key => ({
                        label: key, filterText: key, sortText: key,
                        kind: monaco.languages.CompletionItemKind.Variable,
                        insertText: key
                    }));
                }

                const rawVars   = _GobalModel.get('variables') || {};
                const variables = Object.fromEntries(
                    Object.entries(Object.assign(
                        {},
                        Object.fromEntries(_GlobalVariableCollection.toJSON().map(v => [`GLOBAL:${v.name}`, null])),
                        Object.fromEntries(_VariableCollection.toJSON().map(v => [v.name, null])),
                        rawVars
                    )).sort(([a], [b]) => {
                        const aIn = a in rawVars, bIn = b in rawVars;
                        return aIn !== bIn ? (aIn ? -1 : 1) : a.localeCompare(b);
                    })
                );

                // [[ → список переменных с историей
                if (textBefore.endsWith('[[')) {
                    _variableHistory = _variableHistory.filter(k => k in variables);
                    return Object.entries(variables).map(([key, value]) => {
                        const histIdx    = _variableHistory.indexOf(key);
                        const sortPrefix = histIdx !== -1 ? `0_${String(histIdx).padStart(4, '0')}` : '1';
                        return {
                            label:         key,
                            filterText:    key,
                            sortText:      `${sortPrefix}_${key}`,
                            kind:          histIdx !== -1 && histIdx < 5
                                               ? monaco.languages.CompletionItemKind.Function
                                               : monaco.languages.CompletionItemKind.Variable,
                            documentation: JSON.stringify(value, null, 2).slice(0, 200),
                            insertText:    key,
                            command:       { id: 'trackVar', arguments: [key] }
                        };
                    });
                }

                // [[VARNAME]].path. или [[VARNAME.path.
                const match = textBefore.match(/\[\[([\w:]+)\]\]([\s\S]+)/)
                           || textBefore.match(/\[\[([\w:]+)([\s\S]+)/);
                if (!match) return [];

                const [, varName, path] = match;
                if (variables[varName] === undefined || variables[varName] === null) return [];

                let current = variables[varName];
                try {
                    if (path) {
                        const parts = path.slice(1).split('.').filter(Boolean);
                        for (const part of parts) {
                            const atM  = part.match(/^at\((\d+)\)$/);
                            const valM = part.match(/^val\("((?:\\.|[^"])*)"\)$/);
                            if      (atM)  current = current[parseInt(atM[1], 10)];
                            else if (valM) current = current[valM[1].replace(/\\"/g, '"')];
                            else           current = current[part];
                        }
                    }
                } catch (e) { /* путь не найден */ }

                let suggestions = [];
                try {
                    suggestions = await getTsSuggestionsByExpr(dslPathToJsExpr(varName, path), variables);

                    if (current && typeof current === 'object') {
                        const isArray = Array.isArray(current);
                        for (const key of Object.keys(current)) {
                            const insertText = isArray
                                ? `at(${key})`
                                : /^[A-Za-z_$][\w$]*$/.test(key)
                                    ? key
                                    : `val("${key.replace(/"/g, '\\"')}")`;
                            suggestions.push({
                                label:      key,
                                kind:       monaco.languages.CompletionItemKind.Field,
                                insertText,
                                filterText: key,
                                sortText:   `\x00${key}`
                            });
                        }
                    }
                } catch (e) { prompt('', e); }

                return suggestions;
            },

            resolveCompletionItem: item => Object.assign({}, item)
        };
    }


    // ── Создание редактора ────────────────────

    global.createTextEditor = function (element, options, isPrettyPrint, primitivesEnabled, isCodeEditor) {
        if ($(element).attr('data-installed') === 'true') {
            const existing = _editorRegistry.find(e => e.node === $(element)[0]);
            if (existing) return existing.editor;
        }

        const createEditorHandler = monaco.editor.onDidCreateEditor(editor => {
            _MainView.trigger('monacoEditorCreated', editor);
            createEditorHandler.dispose();
        });
        const createModelHandler = monaco.editor.onDidCreateModel(model => {
            _MainView.trigger('monacoModelCreated', model);
            createModelHandler.dispose();
        });

        initMonacoLanguages();

        const editor = monaco.editor.create(element, _.extend({
            scrollBeyondLastLine: false,
            language:             primitivesEnabled ? 'textEditorGrammar' : 'textEditor',
            automaticLayout:      true,
            fontSize:             11,
            minimap:              { enabled: false },
            theme:                'textEditorTheme',
            wordWrap:             'on',
            wrappingIndent:       'same',
            autoClosingBrackets:  true,
            autoClosingQuotes:    'always',
            autoSurround:         'languageDefined'
        }, options));

        window.editor = editor;

        global.editorSetupContextMenu(editor, isPrettyPrint);
        setupAutoPairs(editor);

        $(element).attr('data-installed', 'true');
        registerEditor(editor);
        return editor;
    };


    // ── Авто-закрытие скобок ──────────────────

    const AUTO_PAIRS = { '[': ']', '{': '}' };

    function setupAutoPairs(editor) {
        editor.onDidType(text => {
            const close = AUTO_PAIRS[text];
            if (!close) return;

            const pos      = editor.getPosition();
            const model    = editor.getModel();
            const twoChars = model.getLineContent(pos.lineNumber).substring(pos.column - 3, pos.column - 1);

            editor.executeEdits('auto-close', [{
                range: new monaco.Range(pos.lineNumber, pos.column, pos.lineNumber, pos.column),
                text: close
            }]);
            editor.setPosition({ lineNumber: pos.lineNumber, column: pos.column });

            if (twoChars === '[[' || twoChars === '{{') {
                editor.trigger('auto-close', 'editor.action.triggerSuggest', {});
            }
        });

        editor.onKeyDown(e => {
            if (e.keyCode !== monaco.KeyCode.Backspace) return;
            const pos   = editor.getPosition();
            const model = editor.getModel();
            if (!pos || !model) return;

            const charL = model.getValueInRange(new monaco.Range(pos.lineNumber, pos.column - 1, pos.lineNumber, pos.column));
            const charR = model.getValueInRange(new monaco.Range(pos.lineNumber, pos.column,     pos.lineNumber, pos.column + 1));

            if (charL && AUTO_PAIRS[charL] === charR) {
                e.preventDefault();
                e.stopPropagation();
                editor.executeEdits('auto-delete-pair', [{
                    range: new monaco.Range(pos.lineNumber, pos.column - 1, pos.lineNumber, pos.column + 1),
                    text: ''
                }]);
            }
        });
    }


    // ── Контекстное меню ──────────────────────

    global.editorSetupContextMenu = function (editor, addPrettyPrint) {
        if (!editor) return;

        const node       = editor.getDomNode();
        const element    = node.parentNode;
        const model      = editor.getModel();
        const languageId = model && model._languageIdentifier
            ? model._languageIdentifier.language
            : null;
        const isJavascript = languageId === 'javascript';
        let wrapOn = true;

        editor.addAction({
            id: 'var', label: tr('Insert variable'),
            contextMenuGroupId: 'navigation', contextMenuOrder: 0.1,
            run: () => BasVariablesDialog.create($(`a.var[data-result-target="#${element.id}"]`))
        });
        editor.addAction({
            id: 'res', label: tr('Load from file, user input, database'),
            contextMenuGroupId: 'navigation', contextMenuOrder: 0.2,
            run: () => BasResourcesDialog.create($(`a.var[data-result-target="#${element.id}"]`))
        });
        editor.addAction({
            id: 'wrap', label: 'Word Wrap',
            contextMenuGroupId: 'navigation', contextMenuOrder: 0.3,
            run: () => { wrapOn = !wrapOn; editor.updateOptions({ wordWrap: wrapOn ? 'on' : 'off' }); }
        });

        if (addPrettyPrint) {
            editor.addAction({
                id: 'prettyAuto',
                label: isJavascript ? 'Pretty Print' : 'Pretty Print (XML/JSON)',
                contextMenuGroupId: 'navigation', contextMenuOrder: 0.4,
                keybindings: [],
                run: ed => formatCurrentEditor(ed, isJavascript)
            });
        }

        const ALLOWED_MENU_ITEMS = [
            tr('Insert variable'),
            tr('Load from file, user input, database'),
            'Word Wrap', 'Pretty Print', 'Pretty Print (XML/JSON)', 'Cut', 'Copy'
        ];

        editor.onContextMenu(e => {
            setTimeout(() => {
                const menu = node.querySelector('.monaco-menu-container');
                if (!menu || menu.offsetHeight === 0) return;
                const { clientX: x, clientY: y } = e.event.browserEvent;
                menu.style.position = 'fixed';
                menu.style.top      = `${Math.max(0, y)}px`;
                menu.style.left     = `${Math.max(0, x)}px`;
                $(menu).find('li.action-item').each(function () {
                    const $label = $(this).find('a.action-label');
                    if (!$label.length || $label.hasClass('separator')) { $(this).hide(); return; }
                    if (ALLOWED_MENU_ITEMS.indexOf($label.text().trim()) === -1) $(this).hide();
                });
            }, 10);
        });

        setupSuggestHooks(editor);
    };


    // ── Хуки автодополнения ───────────────────

    function setupSuggestHooks(editor) {
        const suggest = editor.getContribution('editor.contrib.suggestController');

        function isFunctionLike(item) {
            const text = typeof item.insertText === 'string'
                ? item.insertText
                : typeof item.label === 'string' ? item.label : '';
            return text.indexOf('(') !== -1;
        }

        function selectArgsInsideParens(insertText) {
            const model = editor.getModel();
            const sel   = editor.getSelection();
            if (!model || !sel) return;

            const funcMatch = String(insertText).match(/^[\s\w$.]*\((.*)\)/);
            if (!funcMatch) return;

            const args       = funcMatch[1];
            const before     = insertText.split('(')[0] + '(';
            const innerStart = sel.positionColumn - insertText.length + before.length;

            editor.setSelection(new monaco.Selection(
                sel.positionLineNumber, innerStart,
                sel.positionLineNumber, innerStart + args.length
            ));
        }

        function handleSuggestionSelected(suggestion) {
            if (!suggestion) return;
            const actual = suggestion._actual || suggestion;
            global.trackVariableUsage(actual.label);
            if (isFunctionLike(actual) && actual.insertText) {
                setTimeout(() => selectArgsInsideParens(actual.insertText), 0);
            }
        }

        const origOnDidSelectItem = suggest._onDidSelectItem.bind(suggest);
        suggest._onDidSelectItem = function (e) {
            if (e && e.suggestion) handleSuggestionSelected(e.suggestion);
            return origOnDidSelectItem(e);
        };
        suggest._widget.onDidSelect(e => {
            if (e && e.suggestion) handleSuggestionSelected(e.suggestion);
        });
    }


    // ── Placeholder-виджет ────────────────────

    global.editorSetPlaceholder = function (editor, placeholder) {
        let domNode = null;

        const widget = {
            getId: () => 'editor.widget.placeholderHint',
            getDomNode: () => {
                if (!domNode) {
                    domNode = document.createElement('div');
                    domNode.style.width        = 'max-content';
                    domNode.style.pointerEvents = 'none';
                    domNode.style.color        = '#aaa';
                    domNode.style.whiteSpace   = 'pre';
                    domNode.innerHTML          = placeholder;
                    editor.applyFontInfo(domNode);
                }
                return domNode;
            },
            getPosition: () => ({
                position:   { lineNumber: 1, column: 1 },
                preference: [monaco.editor.ContentWidgetPositionPreference.EXACT]
            }),
            dispose: () => editor.removeContentWidget(widget)
        };

        function sync() {
            editor.getValue() === '' ? editor.addContentWidget(widget) : editor.removeContentWidget(widget);
        }

        const changeHandler  = editor.onDidChangeModelContent(sync);
        const disposeHandler = editor.onDidDispose(() => {
            changeHandler.dispose();
            widget.dispose();
            disposeHandler.dispose();
        });
        sync();
        return widget;
    };


    // ── Reserved words: декорации + маркеры + hover ──

    const reserved = "print,gc,version,Helper,CsvHelper,HtmlParser,Browser,ScriptWorker,Results1,Results2,Results3,Results4,Results5,Results6,Results7,Results8,Results9,Logger,FactorySolver,EngineRes,ResourceHandlers,Properties,_K,MemoryInfo,ResourceLoader,_template,tr,_L,Cycle,Cycles,_next,_next_or_section,_kill_call_stack,_break,_iterator,_arguments,_do,_repeat,_if,_if_else,_call,_call_section,_result,_set_result,_return,_set_label,_rewind,_goto,_fast_goto,VAR_CYCLE_INDEX,VAR_FOREACH_DATA,LINK_REGEXP,VAR_FOR_EACH_CSS,VAR_FOR_EACH_MATCH,VAR_FOR_EACH_XPATH,IF_ELSE_EXPRESSION,CYCLES,memory_virtual_total,memory_virtual_available,memory_physical_total,memory_physical_available,html_parser_xpath_parse,html_parser_xpath_xml,html_parser_xpath_count,html_parser_xpath_exist,html_parser_xpath_text,html_parser_xpath_xml_list,html_parser_xpath_text_list,_get_function_body,rand,_spintax,proxy_parse,proxy_pack,parse_json,md5,base64_encode,base64_decode,file_read,file_read_base64,file_write,file_write_base64,file_append,file_append_base64,directory_of,directory_create,filename_of,combine_path,encode_string,image_get_dimension,image_central_crop,oauth1_header,csv_parse,csv_generate,date_format,date_format_now,db_date_now,translit,_stop_subscript_execution,fail,die,success,request_variables,debug_variables,_get_actual_http_client,_switch_http_client_main,_switch_http_client_internal,_switch_http_client,_ensure_http_client,on_http_client_loaded,new_http_client,http_client_set_fail_on_error,http_client_was_error,http_client_error_string,http_client_get,http_client_get2,http_client_download,http_client_solve,http_client_post,http_client_get_no_redirect,http_client_get_no_redirect2,http_client_post_no_redirect,http_client_url,http_client_content,http_client_content_base64,http_client_header,http_client_status,http_client_set_header,http_client_clear_header,http_client_proxy,http_client_set_proxy,http_client_get_cookies,http_client_save_cookies,http_client_restore_cookies,http_client_xpath_parse,http_client_xpath_xml,http_client_xpath_text,http_client_xpath_xml_list,http_client_xpath_text_list,http_client_xpath_count,http_client_xpath_exist,HttpClientIndex,_ensure_pop3_client,new_pop3_client,pop3_client_set_config,pop3_client_proxy,pop3_client_was_error,pop3_client_error_string,pop3_client_set_proxy,pop3_client_pull_messages_length,pop3_client_pull_message,pop3_client_messages_length,pop3_client_body,pop3_client_subject,pop3_client_sender,_ensure_imap_client,new_imap_client,imap_client_set_config,imap_client_set_proxy,imap_client_proxy,imap_client_was_error,imap_client_error_string,imap_client_pull_messages_length,imap_client_messages_length,imap_client_search,imap_client_custom_search,imap_client_search_result,imap_client_pull_message,imap_client_message,imap_custom_query,imap_custom_query_result,imap_custom_query_log,waiter_timeout_next,waiter_nofail_next,wait_url,wait_load,wait_memory,waiter_prepare_frames,waiter_create_css_path,waiter_create_match_path,wait_content_visible,wait_css_visible,wait_content,wait_css,wait_async_load,wait,get_element_selector,wait_element,wait_element_visible,BROWSERAUTOMATIONSTUDIO_WAIT_TIMEOUT,BROWSERAUTOMATIONSTUDIO_FULL_LOAD_TIMEOUT,BROWSERAUTOMATIONSTUDIO_WAIT_TIMEOUT_NEXT,BROWSERAUTOMATIONSTUDIO_WAIT_NOFAIL_NEXT,_get_last_record_id,RS,R,RSafe,Refuse,RIsRefused,Reload,RInsert,RSync,RCreate,RTake,RSuccessAll,RFailAll,RDieAll,RInfo,RPick,RPickRandom,RMap,_R,_RKEY,P,PSet,PClear,_ensure_browser_created,_simulate_crush,_settings,new_browser,_mbr,_mar,browser,close_browser,mouse,mouse_up,mouse_down,timezone,geolocation,popupclose,popupselect,render,scroll,_default_move_params,move,_clarify,wait_code,section_end,load,load_instant,open_file_dialog,prompt_result,http_auth_result,screenshot,url,get_cookies,resize,reset,jquery,optimize,save_cookies,restore_cookies,restore_localstorage,page,clear_log,log,log_html,log_success,log_fail,ResultResolve,result,result_html,result_file,css,frame,frame_css,xpath,xpath_all,frame_match,position,match,match_all,all,thread_number,success_number,project_path,fail_number,sleep,script,font_list,onloadjavascript,onloadjavascriptinternal,agent,antigate,rucaptcha,twocaptcha,capmonster,solver_properties_clear,solver_property,dbc,_solver_properties_list,solve,solve_base64,solve_base64_no_fail,solver_failed,progress,progress_value,progress_maximum,suspend,on_fail,clear_on_fail,on_success,clear_on_success,_on_fail,_on_fail_exceed,_on_success_exceed,_finnaly,_clear_on_fail,_on_success,_clear_on_success,_set_max_fail,_set_max_success,DEC,_db_add_record,_db_select_records,_db_delete_records,_db_update_record,_db_add_group,_on_start,native,native_async,general_timeout_next,general_timeout,async_load_timeout,solver_timeout_next,solver_timeout,_preprocess,VAR_WAS_ERROR,VAR_LAST_ERROR,_BAS_SOLVER_PROPERTIES,open_browser,_DEFAULT_MOVE_PARAMS,_set_target,_get_target,_get_network_access_manager,header,header_order,clear_header,proxy,set_proxy,cache_allow,cache_deny,request_allow,request_deny,cache_get_base64,cache_get_string,cache_get_status,cache_clear,cache_data_clear,cache_masks_clear,is_load,get_load_stats,_restrict_popups,_allow_popups,_restrict_downloads,_allow_downloads,_BROWSERAUTOMATIONSTUDIO_TARGET,section_start,_sa,section_insert,_clear_image_data,_set_image_data,_find_image,_image,_wait_image,IMAGE_FINDER,BrowserAutomationStudio_ApplyFingerprint,NumbersParseRecaptcha2,BAS_CapmonsterUpdateImage,BAS_SolveRecaptcha,BAS_CAPMONSTER_IMAGE_ID,_BAS_GETSMSSITECODE,_BAS_PARSEJSONFROMHTTPCLIENT,_sms_ban_thread,_sms_ban_service,_sms_before_request,_BAS_SMSREGAPIREQUEST,_BAS_SMSACTIVATEPIREQUEST,_BAS_SMSPVAREQUEST,_BAS_SMSCONFIRMDATA,_SMS_BAN_THREAD,_SMS_DEBUG,NetworkAccessManager".split(',');

    (function () {
        let _hoverRegistered = false;

        function escapeRE(s) {
            return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        }

        function getLanguageId(model) {
            if (!model) return 'javascript';
            return model.getModeId ? model.getModeId() : model.getLanguageId();
        }

        function getTokenLines(model, langId) {
            try { return monaco.editor.tokenize(model.getValue(), langId); } catch (e) { return []; }
        }

        function isInStringOrComment(model, tokenLines, lineNumber, column) {
            const tokens = tokenLines[lineNumber - 1];
            if (!tokens || !tokens.length) return false;
            const offset   = column - 1;
            const lineText = model.getLineContent(lineNumber);
            for (let i = 0; i < tokens.length; i++) {
                const start = tokens[i].offset;
                const end   = i + 1 < tokens.length ? tokens[i + 1].offset : lineText.length;
                if (offset >= start && offset < end) {
                    const type = tokens[i].type || '';
                    return type.indexOf('string') !== -1 || type.indexOf('comment') !== -1;
                }
            }
            return false;
        }

        function findReservedAssignments(model, tokenLines, words) {
            const items = [];
            for (const word of words) {
                if (!word) continue;
                const pattern = `(^|[^\\.])(\\b${escapeRE(word)}\\b)\\s*=`;
                const matches = model.findMatches(pattern, false, true, false, null, false);
                for (const m of matches) {
                    const r = m.range;
                    if (isInStringOrComment(model, tokenLines, r.startLineNumber, r.startColumn)) continue;
                    const matchText   = model.getValueInRange(r);
                    const localIdx    = matchText.search(new RegExp(`\\b${escapeRE(word)}\\b`));
                    if (localIdx < 0) continue;
                    const startColumn = r.startColumn + localIdx;
                    if (isInStringOrComment(model, tokenLines, r.startLineNumber, startColumn)) continue;
                    items.push({ word, lineNumber: r.startLineNumber, startColumn, endColumn: startColumn + word.length });
                }
            }
            return items;
        }

        function ensureHoverProvider() {
            if (_hoverRegistered) return;
            _hoverRegistered = true;
            monaco.languages.registerHoverProvider('javascript', {
                provideHover(model, position) {
                    try {
                        const info = model.getWordAtPosition(position);
                        if (!info || !info.word) return null;
                        if (reserved.indexOf(info.word) === -1) return null;
                        const langId     = getLanguageId(model);
                        const tokenLines = getTokenLines(model, langId);
                        if (isInStringOrComment(model, tokenLines, position.lineNumber, info.startColumn)) return null;
                        const lineText = model.getLineContent(position.lineNumber);
                        const assignRe = new RegExp(`(^|[^\\.])\\b${escapeRE(info.word)}\\b\\s*=`);
                        if (!assignRe.test(lineText)) return null;
                        return {
                            range:    new monaco.Range(position.lineNumber, info.startColumn, position.lineNumber, info.endColumn),
                            contents: [{ value: '**BAS Reserved**' }, { value: 'Reserved variable name. Use a different name.' }]
                        };
                    } catch (e) { prompt('', e && e.stack ? e.stack : e); return null; }
                }
            });
        }

        function updateReservedWords(editor) {
            try {
                if (!editor || !monaco) return;
                const model  = editor.getModel();
                if (!model) return;
                const langId = getLanguageId(model);
                const old    = editor._reservedDecorations || [];

                if (!editor._reservedWordsListenerAttached) {
                    editor._reservedWordsListenerAttached = true;
                    editor.onDidChangeModelContent(() => updateReservedWords(editor));
                    editor.onDidChangeModel(()         => updateReservedWords(editor));
                }

                ensureHoverProvider();

                if (!reserved.length) {
                    editor._reservedDecorations = editor.deltaDecorations(old, []);
                    monaco.editor.setModelMarkers(model, 'bas-reserved', []);
                    return;
                }

                const tokenLines = getTokenLines(model, langId);
                const found      = findReservedAssignments(model, tokenLines, reserved);

                editor._reservedDecorations = editor.deltaDecorations(old, found.map(item => ({
                    range:   new monaco.Range(item.lineNumber, item.startColumn, item.lineNumber, item.endColumn),
                    options: { inlineClassName: 'reserved-word' }
                })));

                monaco.editor.setModelMarkers(model, 'bas-reserved', found.map(item => ({
                    startLineNumber: item.lineNumber, startColumn: item.startColumn,
                    endLineNumber:   item.lineNumber, endColumn:   item.endColumn,
                    message:  `BAS Reserved variable name "${item.word}". Use a different name.`,
                    severity: monaco.Severity.Error
                })));
            } catch (e) { prompt('', e && e.stack ? e.stack : e); }
        }

        global.markReservedWords = updateReservedWords;
    })();


    // ── Стили reserved-word ───────────────────

    const _style = document.createElement('style');
    _style.textContent = '.monaco-editor .reserved-word { color: red !important; font-weight: 600; }';
    document.head.appendChild(_style);

})(window);

define('editor-core', [], function () { return; });
