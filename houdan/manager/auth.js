// 真实鉴权状态
const { reactive, readonly } = Vue;

const _LS_TOKEN = 'manager_token';
const _LS_STAFF = 'manager_staff';

function _readStaff() {
  try { return JSON.parse(localStorage.getItem(_LS_STAFF) || 'null'); }
  catch { return null; }
}

const state = reactive({
  token: localStorage.getItem(_LS_TOKEN) || '',
  staff: _readStaff(),   // { id, username, real_name, role, ... }
});

export function useAuth() {
  return {
    state: readonly(state),
    isLogged() {
      return !!state.token && !!state.staff;
    },
    setSession(token, staff) {
      state.token = token || '';
      state.staff = staff || null;
      if (token) localStorage.setItem(_LS_TOKEN, token);
      else localStorage.removeItem(_LS_TOKEN);
      if (staff) localStorage.setItem(_LS_STAFF, JSON.stringify(staff));
      else localStorage.removeItem(_LS_STAFF);
    },
    clear() {
      this.setSession('', null);
    },
  };
}
