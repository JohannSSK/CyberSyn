/* ==========================================================================
   photo_scan.js — upload a photo, screen it for personal data, redact.

   The page never keeps the photo: it is read into memory, posted once as
   base64, and the only thing kept afterwards is the redacted copy the
   server returned. A re-scan with a different cover style re-sends the
   same in-memory file.
   ========================================================================== */

(function () {
    "use strict";

    if (!window.Shell.guard()) return;

    var Api = window.Api;
    var Dom = window.Dom;
    var Loading = window.Loading;
    var $ = Dom.$;

    var SCAN_ROUTE = "/api/admin/employee/photo/scan";

    var nodes = {
        dropzone: $("#dropzone"),
        fileInput: $("#file-input"),
        results: $("#scan-results"),
        stage: $("#preview-stage"),
        img: $("#preview-img"),
        overlay: $("#preview-overlay"),
        scanning: $("#preview-scanning"),
        scanStageText: $("#scan-stage-text"),
        meta: $("#preview-meta"),
        verdict: $("#verdict"),
        warnings: $("#scan-warnings"),
        findings: $("#findings"),
        redactControls: $("#redact-controls"),
        modePicker: $("#mode-picker"),
        download: $("#btn-download"),
        again: $("#btn-again")
    };

    var lastFile = null;        // data URL of the photo being worked on
    var lastResult = null;      // last server verdict, for re-rendering
    var mode = "blur";
    var stageTimer = null;

    /* ------------------------------------------------------------------
       Picking a photo
       ------------------------------------------------------------------ */

    Dom.on(nodes.dropzone, "click", function () { nodes.fileInput.click(); });
    Dom.on(nodes.dropzone, "keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            nodes.fileInput.click();
        }
    });
    Dom.on(nodes.fileInput, "change", function () {
        if (nodes.fileInput.files && nodes.fileInput.files[0]) {
            acceptFile(nodes.fileInput.files[0]);
        }
        nodes.fileInput.value = "";
    });

    ["dragenter", "dragover"].forEach(function (type) {
        Dom.on(nodes.dropzone, type, function (e) {
            e.preventDefault();
            nodes.dropzone.classList.add("is-dragover");
        });
    });
    ["dragleave", "drop"].forEach(function (type) {
        Dom.on(nodes.dropzone, type, function (e) {
            e.preventDefault();
            nodes.dropzone.classList.remove("is-dragover");
        });
    });
    Dom.on(nodes.dropzone, "drop", function (e) {
        var files = e.dataTransfer && e.dataTransfer.files;
        if (files && files[0]) acceptFile(files[0]);
    });

    /* A photo on the clipboard should be one keystroke away. */
    Dom.on(document, "paste", function (e) {
        var items = e.clipboardData && e.clipboardData.items;
        if (!items) return;
        for (var i = 0; i < items.length; i++) {
            if (items[i].type.indexOf("image/") === 0) {
                acceptFile(items[i].getAsFile());
                return;
            }
        }
    });

    function acceptFile(file) {
        if (!file) return;
        if (file.size > 12 * 1024 * 1024) {
            Loading.toast("The image is too large (12 MB max).", "error");
            return;
        }
        var reader = new FileReader();
        reader.onload = function () {
            lastFile = String(reader.result || "");
            if (lastFile) runScan();
        };
        reader.onerror = function () {
            Loading.toast("Could not read that file.", "error");
        };
        reader.readAsDataURL(file);
    }

    /* ------------------------------------------------------------------
       The scan
       ------------------------------------------------------------------ */

    var STAGES = ["Detecting faces…", "Reading text (OCR)…",
                  "Matching personal data…", "Covering findings…"];

    function showScanning(on) {
        nodes.scanning.classList.toggle("hidden", !on);
        if (stageTimer) {
            clearInterval(stageTimer);
            stageTimer = null;
        }
        if (on) {
            var step = 0;
            nodes.scanStageText.textContent = STAGES[0];
            stageTimer = setInterval(function () {
                step = Math.min(step + 1, STAGES.length - 1);
                nodes.scanStageText.textContent = STAGES[step];
            }, 2600);
        }
    }

    function runScan() {
        nodes.dropzone.classList.add("hidden");
        nodes.results.classList.remove("hidden");
        nodes.img.src = lastFile;
        nodes.overlay.innerHTML = "";
        nodes.verdict.className = "verdict hidden";
        nodes.warnings.classList.add("hidden");
        nodes.findings.innerHTML = "";
        nodes.meta.textContent = "";
        nodes.download.classList.add("hidden");
        showScanning(true);

        Api.post(SCAN_ROUTE, { image: lastFile, mode: mode }, { timeout: 150000 })
            .then(function (data) {
                lastResult = data;
                renderResult();
            })
            .catch(function (err) {
                Loading.toast(err.message || "The photo could not be scanned.", "error");
                reset();
            })
            .finally(function () { showScanning(false); });
    }

    /* ------------------------------------------------------------------
       Rendering
       ------------------------------------------------------------------ */

    function renderResult() {
        var data = lastResult;
        if (!data) return;

        renderVerdict(data);
        renderWarnings(data);
        renderFindings(data);
        renderMeta(data);

        if (data.blocked && data.redacted_image) {
            nodes.download.classList.remove("hidden");
            nodes.redactControls.classList.remove("hidden");
        } else {
            nodes.redactControls.classList.add("hidden");
        }
        // Boxes go on once the image has its layout size.
        if (nodes.img.complete) {
            renderBoxes(data);
        } else {
            nodes.img.onload = function () { renderBoxes(data); };
        }
    }

    function renderVerdict(data) {
        var v = nodes.verdict;
        v.classList.remove("hidden", "is-blocked", "is-clean");
        var n = data.findings.length;
        if (data.blocked) {
            v.classList.add("is-blocked");
            v.innerHTML = window.Icons.svg("lock", "icon") +
                "<span>Photo blocked — " + n + " personal data " +
                (n === 1 ? "item" : "items") + " found." +
                "<small>The original never left this page. Download the redacted copy below.</small></span>";
        } else {
            v.classList.add("is-clean");
            v.innerHTML = window.Icons.svg("check", "icon") +
                "<span>Clean — no personal data found." +
                "<small>Faces, numbers and document fields were all checked.</small></span>";
        }
    }

    function renderWarnings(data) {
        var box = nodes.warnings;
        if (!data.warnings || !data.warnings.length) {
            box.classList.add("hidden");
            return;
        }
        box.classList.remove("hidden");
        box.innerHTML = "";
        data.warnings.forEach(function (w) {
            box.appendChild(Dom.el("div", null, "⚠ " + w));
        });
    }

    var KIND_ICON = {
        FACE: "profile", GREEK_AFM: "key", GREEK_AMKA: "key",
        GREEK_PHONE: "chat", EMAIL: "send", IBAN: "stats",
        CREDIT_CARD: "key", GREEK_ID: "profile",
        LICENSE_PLATE: "warning", DOC_FIELD: "edit"
    };

    function renderFindings(data) {
        var list = nodes.findings;
        list.innerHTML = "";
        if (!data.findings.length) {
            list.appendChild(Dom.el("div", "findings-empty",
                "Nothing to cover in this photo."));
            return;
        }
        data.findings.forEach(function (f, i) {
            var row = Dom.el("div", "finding-row");
            row.innerHTML =
                window.Icons.svg(KIND_ICON[f.kind] || "warning", "icon") +
                '<span class="finding-main">' +
                '<span class="finding-kind">' + Dom.esc(labelFor(f)) + "</span>" +
                (f.detail
                    ? '<span class="finding-detail">' + Dom.esc(f.detail) + "</span>"
                    : "") +
                "</span>" +
                '<span class="finding-score">' + Math.round(f.score * 100) + "%</span>";
            row.addEventListener("mouseenter", function () { hotBox(i, true); });
            row.addEventListener("mouseleave", function () { hotBox(i, false); });
            list.appendChild(row);
        });
    }

    function labelFor(f) {
        /* The interface language decides which label shows. */
        var greek = (window.I18n && window.I18n.current && window.I18n.current() === "el");
        return greek ? f.label_el : f.label_en;
    }

    function renderMeta(data) {
        var secs = (data.scan_ms / 1000).toFixed(1);
        var engines = [];
        if (data.engines && data.engines.faces && data.engines.faces !== "none") {
            engines.push("faces: " + data.engines.faces);
        }
        if (data.engines && data.engines.ocr && data.engines.ocr !== "none") {
            engines.push("text: " + data.engines.ocr);
        }
        nodes.meta.textContent =
            data.width + "×" + data.height + " px · scanned in " + secs + " s" +
            (engines.length ? " · " + engines.join(" · ") : "");
    }

    function renderBoxes(data) {
        var overlay = nodes.overlay;
        overlay.innerHTML = "";
        var shownW = nodes.img.clientWidth;
        if (!shownW || !data.width) return;
        var scale = shownW / data.width;
        data.findings.forEach(function (f, i) {
            f.boxes.forEach(function (b) {
                var box = Dom.el("div", "finding-box");
                box.dataset.index = i;
                box.style.left = (b[0] * scale) + "px";
                box.style.top = (b[1] * scale) + "px";
                box.style.width = (b[2] * scale) + "px";
                box.style.height = (b[3] * scale) + "px";
                var tag = Dom.el("span", "finding-tag", labelFor(f));
                box.appendChild(tag);
                overlay.appendChild(box);
            });
        });
    }

    function hotBox(index, on) {
        Dom.$$(".finding-box", nodes.overlay).forEach(function (box) {
            if (Number(box.dataset.index) === index) {
                box.style.background = on
                    ? "color-mix(in srgb, var(--danger) 32%, transparent)" : "";
            }
        });
    }

    /* Resize keeps the boxes glued to their pixels. */
    Dom.on(window, "resize", function () {
        if (lastResult && !nodes.results.classList.contains("hidden")) {
            renderBoxes(lastResult);
        }
    });

    /* ------------------------------------------------------------------
       Controls
       ------------------------------------------------------------------ */

    Dom.on(nodes.modePicker, "click", function (e) {
        var btn = e.target.closest("button[data-mode]");
        if (!btn) return;
        Dom.$$("button", nodes.modePicker).forEach(function (b) {
            b.classList.toggle("is-active", b === btn);
        });
        if (btn.dataset.mode !== mode) {
            mode = btn.dataset.mode;
            if (lastFile) runScan();
        }
    });

    Dom.on(nodes.download, "click", function () {
        if (!lastResult || !lastResult.redacted_image) return;
        var a = document.createElement("a");
        a.href = lastResult.redacted_image;
        a.download = "cybersyn-redacted.jpg";
        document.body.appendChild(a);
        a.click();
        a.remove();
        Loading.toast("Redacted copy downloaded.", "success");
    });

    Dom.on(nodes.again, "click", reset);

    function reset() {
        lastFile = null;
        lastResult = null;
        nodes.results.classList.add("hidden");
        nodes.dropzone.classList.remove("hidden");
        nodes.img.removeAttribute("src");
        nodes.overlay.innerHTML = "";
    }
})();
