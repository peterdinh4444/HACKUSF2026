/** Require exactly 6 digits before “Verify and continue” submits. */
(function () {
  const form = document.getElementById("verify-email-form");
  const input = document.getElementById("verify-email-code");
  const btn = document.getElementById("verify-email-submit");
  if (!form || !input || !btn) return;

  btn.disabled = true;

  function digitsOnly() {
    return input.value.replace(/\D/g, "").slice(0, 6);
  }

  function sync() {
    const d = digitsOnly();
    if (input.value !== d) input.value = d;
    btn.disabled = d.length !== 6;
  }

  input.addEventListener("input", sync);
  input.addEventListener("paste", () => requestAnimationFrame(sync));
  form.addEventListener("submit", (e) => {
    if (digitsOnly().length !== 6) {
      e.preventDefault();
      input.focus();
    }
  });

  sync();
})();
