(() => {
  const input = document.getElementById("fname");
  const focused = document.getElementById("focused");
  const value = document.getElementById("value");
  const submitted = document.getElementById("submitted");
  const form = document.getElementById("form");
  const clear = document.getElementById("clear");

  function refresh() {
    focused.textContent = document.activeElement === input ? "yes" : "no";
    value.textContent = input.value ? JSON.stringify(input.value) : "(empty)";
  }

  input.addEventListener("focus", refresh);
  input.addEventListener("blur", refresh);
  input.addEventListener("input", refresh);

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    submitted.textContent = input.value ? JSON.stringify(input.value) : "(empty)";
    refresh();
  });

  clear.addEventListener("click", () => {
    input.value = "";
    submitted.textContent = "(none)";
    input.focus();
    refresh();
  });

  refresh();
})();

