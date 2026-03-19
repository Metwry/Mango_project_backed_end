import { sleep } from 'k6';
import {
  buildScenario,
  checkStatus,
  defaultSnapshotWindow,
  envInt,
  login,
  request,
} from './lib/common.js';

export const options = {
  scenarios: {
    query_path: buildScenario('p2-queries', [
      { duration: '30s', target: 10 },
      { duration: '1m', target: 30 },
      { duration: '1m', target: 60 },
      { duration: '30s', target: 0 },
    ]),
  },
  thresholds: {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(95)<1200', 'p(99)<2500'],
  },
};

export function setup() {
  return login();
}

function snapshotAccounts(accessToken) {
  const level = __ENV.SNAPSHOT_LEVEL || 'M15';
  const window = defaultSnapshotWindow(level);
  const response = request('GET', '/api/snapshot/accounts/', {
    token: accessToken,
    query: {
      level,
      start_time: __ENV.SNAPSHOT_START_TIME || window.start,
      end_time: __ENV.SNAPSHOT_END_TIME || window.end,
      limit: envInt('SNAPSHOT_LIMIT', 2000),
      account_id: envInt('SNAPSHOT_ACCOUNT_ID', 0) || '',
    },
    tags: { name: 'query_snapshot_accounts' },
  });
  checkStatus(response, [200, 400], 'snapshot accounts');
}

function snapshotPositions(accessToken) {
  const level = __ENV.SNAPSHOT_LEVEL || 'M15';
  const window = defaultSnapshotWindow(level);
  const response = request('GET', '/api/snapshot/positions/', {
    token: accessToken,
    query: {
      level,
      start_time: __ENV.SNAPSHOT_START_TIME || window.start,
      end_time: __ENV.SNAPSHOT_END_TIME || window.end,
      limit: envInt('SNAPSHOT_LIMIT', 2000),
      account_id: envInt('SNAPSHOT_ACCOUNT_ID', 0) || '',
      instrument_id: envInt('SNAPSHOT_INSTRUMENT_ID', 0) || '',
    },
    tags: { name: 'query_snapshot_positions' },
  });
  checkStatus(response, [200, 400], 'snapshot positions');
}

function investmentHistory(accessToken) {
  const response = request('GET', '/api/investment/history/', {
    token: accessToken,
    query: {
      limit: envInt('HISTORY_LIMIT', 100),
      offset: Math.floor(Math.random() * envInt('HISTORY_MAX_OFFSET', 300)),
      account_id: envInt('HISTORY_ACCOUNT_ID', 0) || '',
      instrument_id: envInt('HISTORY_INSTRUMENT_ID', 0) || '',
    },
    tags: { name: 'query_investment_history' },
  });
  checkStatus(response, [200, 400], 'investment history');
}

function transactions(accessToken) {
  const response = request('GET', '/api/user/transactions/', {
    token: accessToken,
    query: {
      activity_type: __ENV.TX_ACTIVITY_TYPE || 'manual',
      page: Math.floor(Math.random() * envInt('TX_MAX_PAGE', 10)) + 1,
      page_size: envInt('TX_PAGE_SIZE', 50),
    },
    tags: { name: 'query_transactions' },
  });
  checkStatus(response, [200, 400], 'transactions');
}

function positions(accessToken) {
  const response = request('GET', '/api/investment/positions/', {
    token: accessToken,
    tags: { name: 'query_positions' },
  });
  checkStatus(response, 200, 'positions');
}

export default function (auth) {
  const accessToken = auth.access;
  const roll = Math.random();

  if (roll < 0.25) {
    snapshotAccounts(accessToken);
  } else if (roll < 0.5) {
    snapshotPositions(accessToken);
  } else if (roll < 0.75) {
    transactions(accessToken);
  } else if (roll < 0.9) {
    investmentHistory(accessToken);
  } else {
    positions(accessToken);
  }

  sleep(Number(__ENV.SLEEP_SECONDS || 0.5));
}
