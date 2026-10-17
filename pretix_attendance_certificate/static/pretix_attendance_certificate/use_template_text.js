// Kept as a static file (not an inline <script>): pretix's Content-Security-Policy
// only allows scripts served from its static domain.
(function () {
    var btn = document.getElementById("attendance-certificate-use-template-text");
    var select = document.getElementById("id_layout");
    var dataEl = document.getElementById("attendance-certificate-mail-texts");
    if (!btn || !select || !dataEl) {
        return;
    }
    var texts = JSON.parse(dataEl.textContent);
    btn.addEventListener("click", function () {
        var entry = texts[select.value];
        if (!entry) {
            return;
        }
        entry.subject.forEach(function (value, i) {
            var el = document.getElementById("id_subject_" + i);
            if (el) {
                el.value = value;
            }
        });
        entry.message.forEach(function (value, i) {
            var el = document.getElementById("id_message_" + i);
            if (el) {
                el.value = value;
            }
        });
    });
})();
