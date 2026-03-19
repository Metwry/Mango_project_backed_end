import { sleep } from 'k6';
import {
  buildScenario,
  checkStatus,
  envInt,
  login,
  requirePositiveIntEnv,
  randomMoney,
  randomPrice,
  randomQuantity,
  request,
} from './lib/common.js';

const hotTransactionIds = [];
const hotTransferIds = [];

const buyWeight = envInt('BUY_WEIGHT', 30);
const sellWeight = envInt('SELL_WEIGHT', 25);
const manualTxWeight = envInt('MANUAL_TX_WEIGHT', 25);
const transferWeight = envInt('TRANSFER_WEIGHT', 20);
const hotReverseWeight = envInt('HOT_REVERSE_WEIGHT', 10);

export const options = {
  scenarios: {
    funds_hot_path: buildScenario('p0-funds', [
      { duration: '30s', target: 10 },
      { duration: '1m', target: 30 },
      { duration: '1m', target: 60 },
      { duration: '30s', target: 0 },
    ]),
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<1000', 'p(99)<2000'],
  },
};

export function setup() {
  requirePositiveIntEnv('TX_ACCOUNT_ID');
  requirePositiveIntEnv('TRANSFER_FROM_ACCOUNT_ID');
  requirePositiveIntEnv('TRANSFER_TO_ACCOUNT_ID');
  requirePositiveIntEnv('BUY_INSTRUMENT_ID');
  requirePositiveIntEnv('BUY_CASH_ACCOUNT_ID');
  return login();
}

function rememberId(store, value) {
  if (!value) {
    return;
  }
  store.push(value);
  if (store.length > 100) {
    store.shift();
  }
}

function createManualTransaction(accessToken) {
  const response = request('POST', '/api/user/transactions/', {
    token: accessToken,
    body: {
      counterparty: `k6-manual-${Date.now()}`,
      amount: `-${randomMoney(1, 50)}`,
      category_name: 'k6',
      account: envInt('TX_ACCOUNT_ID', 0),
    },
    tags: { name: 'funds_manual_tx' },
  });
  if (checkStatus(response, [201], 'manual transaction')) {
    const txId = response.json('id');
    rememberId(hotTransactionIds, txId);
  }
}

function reverseTransaction(accessToken, txId) {
  const response = request('POST', `/api/user/transactions/${txId}/reverse/`, {
    token: accessToken,
    body: {},
    tags: { name: 'funds_reverse_tx' },
  });
  checkStatus(response, [201, 400, 404], 'reverse transaction');
}

function createTransfer(accessToken) {
  const response = request('POST', '/api/user/transfers/', {
    token: accessToken,
    body: {
      from_account_id: envInt('TRANSFER_FROM_ACCOUNT_ID', 0),
      to_account_id: envInt('TRANSFER_TO_ACCOUNT_ID', 0),
      amount: randomMoney(1, 50),
      note: 'k6 transfer',
    },
    tags: { name: 'funds_transfer' },
  });
  if (checkStatus(response, [201, 400, 409], 'create transfer')) {
    const transferId = response.json('id');
    rememberId(hotTransferIds, transferId);
  }
}

function reverseTransfer(accessToken, transferId) {
  const response = request('POST', `/api/user/transfers/${transferId}/reverse/`, {
    token: accessToken,
    body: {},
    tags: { name: 'funds_reverse_transfer' },
  });
  checkStatus(response, [201, 400, 404], 'reverse transfer');
}

function buy(accessToken) {
  const response = request('POST', '/api/investment/buy/', {
    token: accessToken,
    body: {
      instrument_id: envInt('BUY_INSTRUMENT_ID', 0),
      quantity: randomQuantity(1, 2),
      price: randomPrice(10, 40),
      cash_account_id: envInt('BUY_CASH_ACCOUNT_ID', 0),
    },
    tags: { name: 'funds_buy' },
  });
  checkStatus(response, [201, 409, 400], 'buy');
}

function sell(accessToken) {
  const response = request('POST', '/api/investment/sell/', {
    token: accessToken,
    body: {
      instrument_id: envInt('SELL_INSTRUMENT_ID', envInt('BUY_INSTRUMENT_ID', 0)),
      quantity: randomQuantity(1, 2),
      price: randomPrice(10, 40),
      cash_account_id: envInt('SELL_CASH_ACCOUNT_ID', envInt('BUY_CASH_ACCOUNT_ID', 0)),
    },
    tags: { name: 'funds_sell' },
  });
  checkStatus(response, [201, 409, 400], 'sell');
}

export default function (auth) {
  const accessToken = auth.access;
  const roll = Math.random() * (buyWeight + sellWeight + manualTxWeight + transferWeight + hotReverseWeight);

  if (roll < hotReverseWeight && hotTransactionIds.length > 0) {
    reverseTransaction(accessToken, hotTransactionIds[Math.floor(Math.random() * hotTransactionIds.length)]);
  } else if (roll < hotReverseWeight + transferWeight && hotTransferIds.length > 0) {
    reverseTransfer(accessToken, hotTransferIds[Math.floor(Math.random() * hotTransferIds.length)]);
  } else if (roll < hotReverseWeight + transferWeight + buyWeight) {
    buy(accessToken);
  } else if (roll < hotReverseWeight + transferWeight + buyWeight + sellWeight) {
    sell(accessToken);
  } else if (roll < hotReverseWeight + transferWeight + buyWeight + sellWeight + manualTxWeight) {
    createManualTransaction(accessToken);
  } else {
    createTransfer(accessToken);
  }

  const fixedHotTxId = envInt('HOT_TX_ID', 0);
  if (fixedHotTxId > 0 && Math.random() < 0.2) {
    reverseTransaction(accessToken, fixedHotTxId);
  }

  const fixedHotTransferId = envInt('HOT_TRANSFER_ID', 0);
  if (fixedHotTransferId > 0 && Math.random() < 0.1) {
    reverseTransfer(accessToken, fixedHotTransferId);
  }

  sleep(Number(__ENV.SLEEP_SECONDS || 0.5));
}
