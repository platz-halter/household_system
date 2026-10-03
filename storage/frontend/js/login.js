import { login, loginWithAuthentik } from "./auth.js";
import { showToast } from "./toast.js";
import { icons } from "./icons.js";
import { navigate } from "./router.js";

export function renderLogin(container) {
  container.innerHTML = `
    <div class="container-narrow center" style="min-height: calc(100vh - var(--topbar-height)); flex-direction: column;">
      <div style="margin-bottom: var(--space-6);">${icons.box}</div>

      <button class="btn btn-primary btn-block" id="authentik-login-btn">Log in with Authentik</button>

      <button class="btn btn-ghost" id="toggle-local-login" style="margin-top: var(--space-4);">
        Use a local account instead
      </button>

      <form id="login-form" class="stack hidden" style="width: 100%; margin-top: var(--space-4);">
        <div class="field">
          <label for="login-username">Username</label>
          <input class="input" id="login-username" autocomplete="username" required />
        </div>
        <div class="field">
          <label for="login-password">Password</label>
          <input class="input" id="login-password" type="password" autocomplete="current-password" required />
        </div>
        <button class="btn btn-block" type="submit" id="login-submit">Log in</button>
      </form>
    </div>
  `;

  container.querySelector("#authentik-login-btn").addEventListener("click", async () => {
    // On success this redirects the browser away and never returns. On
    // failure (auth service unreachable, or Authentik simply not
    // configured yet on a fresh deploy) it throws instead — show that
    // as an ordinary toast rather than an unhandled rejection.
    try {
      await loginWithAuthentik();
    } catch {
      showToast("Authentik isn't reachable right now — try a local account instead", "danger");
    }
  });

  const form = container.querySelector("#login-form");
  const toggleBtn = container.querySelector("#toggle-local-login");
  toggleBtn.addEventListener("click", () => {
    const nowShown = form.classList.toggle("hidden") === false;
    toggleBtn.textContent = nowShown ? "Use Authentik instead" : "Use a local account instead";
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const submitBtn = container.querySelector("#login-submit");
    const username = container.querySelector("#login-username").value.trim();
    const password = container.querySelector("#login-password").value;

    submitBtn.disabled = true;
    submitBtn.textContent = "Logging in…";
    try {
      await login(username, password);
      navigate("/overview");
    } catch (err) {
      showToast(err.message || "Login failed", "danger");
      submitBtn.disabled = false;
      submitBtn.textContent = "Log in";
    }
  });
}
