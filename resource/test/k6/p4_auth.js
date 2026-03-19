import { sleep } from 'k6';
import { check } from 'k6';
import {
  buildScenario,
  checkStatus,
  envBool,
  iterationSuffix,
  login,
  request,
  requireEnv,
} from './lib/common.js';

const vuState = {
  refreshToken: '',
};

export const options = {
  scenarios: {
    auth_path: buildScenario('p4-auth', [
      { duration: '30s', target: 10 },
      { duration: '1m', target: 30 },
      { duration: '1m', target: 60 },
      { duration: '30s', target: 0 },
    ]),
  },
  thresholds: {
    http_req_failed: ['rate<0.03'],
    http_req_duration: ['p(95)<1000', 'p(99)<2000'],
  },
};

function doLogin() {
  const auth = login();
  vuState.refreshToken = auth.refresh;
}

function refreshToken() {
  if (!vuState.refreshToken) {
    doLogin();
  }
  const response = request('POST', '/api/token/refresh/', {
    body: { refresh: vuState.refreshToken },
    tags: { name: 'auth_refresh' },
  });
  const ok = checkStatus(response, [200, 401], 'token refresh');
  if (ok && response.status === 200) {
    check(response, {
      'token refresh returns access': (res) => Boolean(res.json('access')),
    });
  }
}

function sendRegisterCode() {
  const prefix = __ENV.REGISTER_EMAIL_PREFIX || 'k6-register';
  const domain = requireEnv('REGISTER_EMAIL_DOMAIN');
  const response = request('POST', '/api/register/email/code/', {
    body: {
      email: `${prefix}-${iterationSuffix()}@${domain}`,
    },
    tags: { name: 'auth_register_code' },
  });
  checkStatus(response, [200, 400, 500], 'send register code');
}

function sendPasswordResetCode() {
  const resetEmail = requireEnv('RESET_EMAIL');
  const response = request('POST', '/api/password/reset/code/', {
    body: { email: resetEmail },
    tags: { name: 'auth_reset_code' },
  });
  checkStatus(response, [200, 400, 500], 'send password reset code');
}

export default function () {
  const roll = Math.random();

  if (roll < 0.6) {
    doLogin();
  } else if (roll < 0.9) {
    refreshToken();
  } else if (envBool('ENABLE_EMAIL_CODE_FLOW', false) && __ENV.REGISTER_EMAIL_DOMAIN) {
    sendRegisterCode();
  } else if (envBool('ENABLE_RESET_CODE_FLOW', false) && __ENV.RESET_EMAIL) {
    sendPasswordResetCode();
  } else {
    doLogin();
  }

  sleep(Number(__ENV.SLEEP_SECONDS || 0.5));
}
