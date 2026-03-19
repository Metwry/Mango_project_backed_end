import { sleep } from 'k6';
import {
  checkStatus,
  defaultSnapshotWindow,
  envBool,
  envJson,
  envInt,
  login,
  request,
} from './lib/common.js';

const vuState = {
  watchlistAdded: false,
};

export const options = {
  scenarios: {
    soak_mix: {
      executor: 'constant-vus',
      vus: envInt('SOAK_VUS', 20),
      duration: __ENV.SOAK_DURATION || '30m',
      tags: { suite: 'p3-soak-mixed' },
      gracefulStop: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.03'],
    http_req_duration: ['p(95)<1500', 'p(99)<3000'],
  },
};

export function setup() {
  return login();
}

function getMarkets(accessToken) {
  const response = request('GET', '/api/user/markets/', {
    token: accessToken,
    tags: { name: 'soak_markets' },
  });
  checkStatus(response, 200, 'soak markets');
}

function latestQuotes(accessToken) {
  const response = request('POST', '/api/user/markets/quotes/latest/', {
    token: accessToken,
    body: {
      items: envJson('QUOTE_ITEMS_JSON', [{ market: 'US', short_code: 'AAPL' }]),
    },
    tags: { name: 'soak_quotes_latest' },
  });
  checkStatus(response, 200, 'soak latest quotes');
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
      limit: envInt('SNAPSHOT_LIMIT', 500),
    },
    tags: { name: 'soak_snapshot_accounts' },
  });
  checkStatus(response, [200, 400], 'soak snapshot accounts');
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
      limit: envInt('SNAPSHOT_LIMIT', 500),
    },
    tags: { name: 'soak_snapshot_positions' },
  });
  checkStatus(response, [200, 400], 'soak snapshot positions');
}

function maybeWriteWatchlist(accessToken) {
  if (!envBool('ENABLE_WATCHLIST_WRITES', false)) {
    return;
  }
  const method = vuState.watchlistAdded ? 'DELETE' : 'POST';
  const response = request(method, '/api/user/markets/watchlist/', {
    token: accessToken,
    body: { symbol: __ENV.WATCHLIST_SYMBOL || 'AAPL.US' },
    tags: { name: method === 'POST' ? 'soak_watchlist_add' : 'soak_watchlist_delete' },
  });
  if (checkStatus(response, [200, 201, 400], 'soak watchlist write')) {
    vuState.watchlistAdded = method === 'POST' && response.status !== 400;
  }
}

export default function (auth) {
  const accessToken = auth.access;
  const roll = Math.random();

  if (roll < 0.4) {
    getMarkets(accessToken);
  } else if (roll < 0.6) {
    latestQuotes(accessToken);
  } else if (roll < 0.8) {
    snapshotAccounts(accessToken);
  } else if (roll < 0.95) {
    snapshotPositions(accessToken);
  } else {
    maybeWriteWatchlist(accessToken);
  }

  sleep(Number(__ENV.SLEEP_SECONDS || 1));
}
