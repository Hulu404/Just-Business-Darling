/* Вход сотрудника и заглушки разделов врача и клиники (FE1). Тема клиники у сотрудника не применяется.
   Мок-вход: POST /staff/login { login, password } → { role, display_name }. Сессия — только в памяти вкладки:
   роль и имя; пароль после запроса не хранится, токенов нет. Настоящий вход — сессия шлюза в FE5/FE6. */
import { ApiError } from './api.js';
import { STAFF_TEXTS as T } from './texts.js';
import { note } from './ui.js';

const HOME = Object.freeze({doctor:'/doctor', manager:'/clinic'});
let session = null;

function renderStaffBar(ctx){
  const bar = document.getElementById('staff-bar');
  if (!bar || !session) return;
  const role = T.role[session.role] || '';
  bar.innerHTML = `<span class="staff-who"><span class="staff-name">${ctx.safe(session.display_name)}</span>`
    + `<span class="staff-role">${ctx.safe(role)}</span></span>`
    + `<button type="button" class="btn text staff-logout" data-action="logout">${ctx.safe(T.logout)}</button>`;
  bar.hidden = false;
  bar.querySelector('[data-action="logout"]').addEventListener('click', () => {
    session = null;
    ctx.go('/staff/login');
  });
}

function loginView(ctx){
  const L = T.login;
  return `<section class="card staff-card" aria-labelledby="staff-title">
  <h1 id="staff-title">${ctx.safe(L.title)}</h1>
  <p class="muted">${ctx.safe(L.subtitle)}</p>
  <form class="staff-form" novalidate>
    <div class="field"><label for="staff-login">${ctx.safe(L.login)}</label>
      <input class="input" id="staff-login" name="login" type="text" autocomplete="username" autocapitalize="off" spellcheck="false"></div>
    <div class="field"><label for="staff-password">${ctx.safe(L.password)}</label>
      <input class="input" id="staff-password" name="password" type="password" autocomplete="current-password"></div>
    <div id="staff-error" class="staff-error"></div>
    <button type="submit" class="btn block">${ctx.safe(L.action)}</button>
  </form>
  ${note(L.demo_hint)}
</section>`;
}

function showLoginError(form, ctx, text){
  const box = form.querySelector('#staff-error');
  box.innerHTML = note(text, {role:'alert'});
  form.querySelectorAll('input').forEach(input => input.setAttribute('aria-describedby', 'staff-error'));
}

const login = Object.freeze({
  render(view, ctx){
    view.innerHTML = loginView(ctx);
    const form = view.querySelector('form');
    const loginInput = form.elements.login;
    const passwordInput = form.elements.password;
    const button = form.querySelector('button[type="submit"]');
    let busy = false;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (busy) return;
      const values = {login:loginInput.value.trim(), password:passwordInput.value};
      if (!values.login || !values.password){
        showLoginError(form, ctx, T.login.empty);
        (values.login ? passwordInput : loginInput).focus();
        return;
      }
      busy = true;
      button.disabled = true;
      button.textContent = T.login.pending;
      try {
        const user = await ctx.api('POST', '/staff/login', values);
        session = Object.freeze({role:user.role, display_name:user.display_name});
        passwordInput.value = '';
        ctx.go(HOME[user.role] || '/staff/login');
        return;
      } catch (err){
        if (!form.isConnected) return;
        const wrong = err instanceof ApiError && (err.status === 401 || err.status === 422);
        showLoginError(form, ctx, wrong ? T.login.wrong : T.login.unavailable);
        passwordInput.value = '';
        passwordInput.focus();
      } finally {
        values.password = '';
        busy = false;
        if (form.isConnected){
          button.disabled = false;
          button.textContent = T.login.action;
        }
      }
    });
    loginInput.focus();
  }
});

function forbidden(view, ctx){
  const F = T.forbidden;
  view.innerHTML = `<section class="card state staff-card"><h1>${ctx.safe(F.title)}</h1><p>${ctx.safe(F.body)}</p>`
    + `<button type="button" class="btn block" data-action="to-login">${ctx.safe(F.action)}</button></section>`;
  view.querySelector('[data-action="to-login"]').addEventListener('click', () => ctx.go('/staff/login'));
}

/* Заглушка раздела: видна только своей роли, иначе «этот раздел вам недоступен» */
function stub(role, texts){
  return Object.freeze({
    render(view, ctx){
      if (!session || session.role !== role){
        forbidden(view, ctx);
        return;
      }
      renderStaffBar(ctx);
      view.innerHTML = `<section class="card staff-stub"><h1>${ctx.safe(texts.title)}</h1>${note(texts.stub)}</section>`;
    }
  });
}

export const screens = Object.freeze({
  login,
  doctor:stub('doctor', T.doctor),
  clinic:stub('manager', T.clinic)
});
