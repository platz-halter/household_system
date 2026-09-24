import { login } from "./auth.js";
import { showToast } from "./toast.js";
import { icons } from "./icons.js";

export function renderLogin(container) {
  container.innerHTML = `
    <div class="container-narrow center" style="min-height: calc(100vh - var(--topbar-height)); flex-direction: column;">
      <div style="margin-bottom: var(--space-6);">${icons.box}</div>
      <form id="login-form" class="stack" style="width: 100%;">
        <div class="field">
          <label for="login-username">Username</label>
          <input class="input" id="login-username" autocomplete="username" required />
        </div>
        <div class="field">
          <label for="login-password">Password</label>
          <input class="input" id="login-password" type="password" autocomplete="current-password" required />
        </div>
        <button class="btn btn-primary btn-block" type="submit" id="login-submit">Log in</button>
      </form>
    </div>
  `;

  const form = container.querySelector("#login-form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const submitBtn = container.querySelector("#login-submit");
    const username = container.querySelector("#login-username").value.trim();
    const password = container.querySelector("#login-password").value;

    submitBtn.disabled = true;
    submitBtn.textContent = "Logging in…";
    try {
      await login(username, password);
      window.location.hash = "#/overview";
    } catch (err) {
      showToast(err.message || "Login failed", "danger");
      submitBtn.disabled = false;
      submitBtn.textContent = "Log in";
    }
  });
}
