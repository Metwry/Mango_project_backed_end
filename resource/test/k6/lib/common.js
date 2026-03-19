import http from 'k6/http';
import exec from 'k6/execution';
import { check, fail } from 'k6';

export const baseUrl = (__ENV.BASE_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');

export function envInt(name, defaultValue) {
  const raw = __ENV[name];
  if (raw === undefined || raw === null || raw === '') {
    return defaultValue;
  }
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed)) {
    fail(`Environment variable ${name} must be an integer.`);
  }
  return parsed;
}

export function envBool(name, defaultValue = false) {
  const raw = (__ENV[name] || '').trim().toLowerCase();
  if (!raw) {
    return defaultValue;
  }
  return ['1', 'true', 'yes', 'on'].includes(raw);
}

export function envJson(name, fallbackValue) {
  const raw = __ENV[name];
  if (!raw) {
    return fallbackValue;
  }
  try {
    return JSON.parse(raw);
  } catch (error) {
    fail(`Environment variable ${name} must be valid JSON: ${error}`);
  }
}

export function requireEnv(name) {
  const value = (__ENV[name] || '').trim();
  if (!value) {
    fail(`Missing required environment variable: ${name}`);
  }
  return value;
}

export function requirePositiveIntEnv(name) {
  const value = envInt(name, 0);
  if (value <= 0) {
    fail(`Environment variable ${name} must be a positive integer.`);
  }
  return value;
}

export function buildStages(defaults) {
  return defaults.map((stage, index) => ({
    duration: __ENV[`STAGE_${index + 1}_DURATION`] || stage.duration,
    target: envInt(`STAGE_${index + 1}_TARGET`, stage.target),
  }));
}

export function buildScenario(name, defaults, gracefulStop = '10s') {
  return {
    executor: 'ramping-vus',
    startVUs: envInt('START_VUS', 1),
    gracefulRampDown: gracefulStop,
    stages: buildStages(defaults),
    tags: { suite: name },
  };
}

export function request(method, path, { token = '', body, query = {}, tags = {} } = {}) {
  const queryString = Object.entries(query)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    .join('&');
  const url = `${baseUrl}${path}${queryString ? `?${queryString}` : ''}`;
  const headers = {
    Accept: 'application/json',
  };
  let payload = null;

  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  return http.request(method, url, payload, {
    headers,
    tags,
  });
}

export function checkStatus(response, expectedStatuses, label) {
  const accepted = Array.isArray(expectedStatuses) ? expectedStatuses : [expectedStatuses];
  return check(response, {
    [`${label} status in ${accepted.join('/')}`]: (res) => accepted.includes(res.status),
  });
}

export function login() {
  const identifier = (__ENV.USERNAME || __ENV.EMAIL || '').trim();
  const password = requireEnv('PASSWORD');
  if (!identifier) {
    fail('Provide USERNAME or EMAIL for authenticated k6 scenarios.');
  }

  const body = __ENV.EMAIL
    ? { email: __ENV.EMAIL, password }
    : { username: __ENV.USERNAME, password };
  const response = request('POST', '/api/login/', {
    body,
    tags: { name: 'login' },
  });
  const ok = check(response, {
    'login status is 200': (res) => res.status === 200,
    'login returns access token': (res) => Boolean(res.json('access')),
    'login returns refresh token': (res) => Boolean(res.json('refresh')),
  });
  if (!ok) {
    fail(`Login failed: status=${response.status} body=${response.body}`);
  }
  return {
    access: response.json('access'),
    refresh: response.json('refresh'),
    user: response.json('user'),
  };
}

export function randomMoney(minValue, maxValue) {
  const next = minValue + Math.random() * (maxValue - minValue);
  return next.toFixed(2);
}

export function randomQuantity(minValue = 1, maxValue = 3) {
  const next = minValue + Math.random() * (maxValue - minValue);
  return next.toFixed(6);
}

export function randomPrice(minValue = 10, maxValue = 100) {
  const next = minValue + Math.random() * (maxValue - minValue);
  return next.toFixed(6);
}

export function pick(items) {
  return items[Math.floor(Math.random() * items.length)];
}

export function maybe(value, fallbackValue) {
  return value === undefined || value === null || value === '' ? fallbackValue : value;
}

export function iterationSuffix() {
  return `${exec.vu.idInTest}-${exec.scenario.iterationInTest}`;
}

export function isoNowMinusHours(hours) {
  return new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();
}

export function defaultSnapshotWindow(level) {
  if (level === 'M15') {
    return {
      start: isoNowMinusHours(24),
      end: new Date().toISOString(),
    };
  }
  if (level === 'H4') {
    return {
      start: isoNowMinusHours(24 * 30),
      end: new Date().toISOString(),
    };
  }
  return {
    start: isoNowMinusHours(24 * 90),
    end: new Date().toISOString(),
  };
}
