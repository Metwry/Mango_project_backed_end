import { sleep } from 'k6';
import {
  buildScenario,
  checkStatus,
  envBool,
  envJson,
  login,
  request,
} from './lib/common.js';

const vuState = {
  watchlistAdded: false,
};

export const options = {
  scenarios: {
    market_hot_path: buildScenario('p1-market', [
      { duration: '30s', target: 20 },
      { duration: '1m', target: 50 },
      { duration: '1m', target: 100 },
      { duration: '30s', target: 0 },
    ]),
  },
  thresholds: {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(95)<500', 'p(99)<1200'],
  },
};

export function setup() {
  return login();
}

function getMarkets(accessToken) {
  const response = request('GET', '/api/user/markets/', {
    token: accessToken,
    tags: { name: 'market_overview' },
  });
  checkStatus(response, 200, 'get markets');
}

function latestQuotes(accessToken) {
  const response = request('POST', '/api/user/markets/quotes/latest/', {
    token: accessToken,
    body: {
      items: envJson('QUOTE_ITEMS_JSON', [{ market: 'US', short_code: 'AAPL' }]),
    },
    tags: { name: 'market_latest_quotes' },
  });
  checkStatus(response, 200, 'latest quotes');
}

function getIndices(accessToken) {
  const response = request('GET', '/api/user/markets/indices/', {
    token: accessToken,
    tags: { name: 'market_indices' },
  });
  checkStatus(response, 200, 'get indices');
}

function getFxRates(accessToken) {
  const response = request('GET', '/api/user/markets/fx-rates/', {
    token: accessToken,
    query: { base: __ENV.FX_BASE || 'USD' },
    tags: { name: 'market_fx' },
  });
  checkStatus(response, [200, 400], 'get fx rates');
}

function addWatchlist(accessToken) {
  const response = request('POST', '/api/user/markets/watchlist/', {
    token: accessToken,
    body: { symbol: __ENV.WATCHLIST_SYMBOL || 'AAPL.US' },
    tags: { name: 'market_watchlist_add' },
  });
  if (checkStatus(response, [200, 201, 400], 'add watchlist')) {
    vuState.watchlistAdded = response.status !== 400;
  }
}

function deleteWatchlist(accessToken) {
  const response = request('DELETE', '/api/user/markets/watchlist/', {
    token: accessToken,
    body: { symbol: __ENV.WATCHLIST_SYMBOL || 'AAPL.US' },
    tags: { name: 'market_watchlist_delete' },
  });
  if (checkStatus(response, [200, 400], 'delete watchlist')) {
    vuState.watchlistAdded = false;
  }
}

export default function (auth) {
  const accessToken = auth.access;
  const roll = Math.random();
  const enableWrites = envBool('ENABLE_WATCHLIST_WRITES', true);

  if (roll < 0.55) {
    getMarkets(accessToken);
  } else if (roll < 0.8) {
    latestQuotes(accessToken);
  } else if (roll < 0.9) {
    getIndices(accessToken);
  } else if (roll < 0.97) {
    getFxRates(accessToken);
  } else if (enableWrites && !vuState.watchlistAdded) {
    addWatchlist(accessToken);
  } else if (enableWrites) {
    deleteWatchlist(accessToken);
  } else {
    getMarkets(accessToken);
  }

  sleep(Number(__ENV.SLEEP_SECONDS || 0.3));
}
