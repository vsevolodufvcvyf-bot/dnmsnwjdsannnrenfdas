/** Сгенерировано scripts/seed.mjs. */
export const SEED = {
  "version": 1,
  "note": "Веса сняты с 15-минуток BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT. На контрольном куске средний результат -0.35R за 115 сделок.",
  "trainedOn": [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT"
  ],
  "test": {
    "symbols": [
      "BTCUSDT",
      "ETHUSDT",
      "SOLUSDT",
      "BNBUSDT"
    ],
    "interval": "15m",
    "trades": 115,
    "wins": 36,
    "meanR": -0.351,
    "trainTrades": 174,
    "trainMeanR": -0.071
  },
  "weights": {
    "cup_handle": {
      "ewma": -1.1,
      "samples": 4,
      "wins": 0,
      "losses": 4,
      "sumR": -4.4
    },
    "morning_star": {
      "ewma": -1.1,
      "samples": 2,
      "wins": 0,
      "losses": 2,
      "sumR": -2.2
    },
    "bull_engulf": {
      "ewma": 0.11409225844606721,
      "samples": 23,
      "wins": 9,
      "losses": 14,
      "sumR": 1.699999999999998
    },
    "bear_engulf": {
      "ewma": -1.1,
      "samples": 2,
      "wins": 0,
      "losses": 2,
      "sumR": -2.2
    },
    "double_bottom": {
      "ewma": -0.2615129949453969,
      "samples": 23,
      "wins": 13,
      "losses": 10,
      "sumR": -2.255289476994474
    },
    "piercing": {
      "ewma": -1.1,
      "samples": 1,
      "wins": 0,
      "losses": 1,
      "sumR": -1.1
    },
    "double_top": {
      "ewma": -0.02821896929214901,
      "samples": 18,
      "wins": 11,
      "losses": 7,
      "sumR": 0.010509676107446131
    },
    "dark_cloud": {
      "ewma": 0.67057785129313,
      "samples": 17,
      "wins": 9,
      "losses": 8,
      "sumR": 8.300000000000004
    },
    "evening_star": {
      "ewma": -0.8300000000000001,
      "samples": 3,
      "wins": 1,
      "losses": 2,
      "sumR": -0.30000000000000027
    },
    "trend_down": {
      "ewma": 0.2967448326597302,
      "samples": 4,
      "wins": 1,
      "losses": 3,
      "sumR": -2.4840262926478327
    },
    "triple_bottom": {
      "ewma": -1.1,
      "samples": 2,
      "wins": 0,
      "losses": 2,
      "sumR": -2.2
    },
    "triple_top": {
      "ewma": -0.6302580993367525,
      "samples": 4,
      "wins": 3,
      "losses": 1,
      "sumR": 0.7963690152752456
    },
    "trend_up": {
      "ewma": -0.732798820379361,
      "samples": 3,
      "wins": 2,
      "losses": 1,
      "sumR": 0.5635508719192517
    },
    "bear_pennant": {
      "ewma": -1.1,
      "samples": 1,
      "wins": 0,
      "losses": 1,
      "sumR": -1.1
    },
    "inv_cup_handle": {
      "ewma": -0.45778241020765575,
      "samples": 14,
      "wins": 4,
      "losses": 10,
      "sumR": 2.402972728097134
    },
    "rounding_bottom": {
      "ewma": 0.6130744762608703,
      "samples": 1,
      "wins": 1,
      "losses": 0,
      "sumR": 0.6130744762608703
    },
    "bull_flag": {
      "ewma": 0.3158640876633544,
      "samples": 6,
      "wins": 3,
      "losses": 3,
      "sumR": 0.31501704989976664
    },
    "range_up": {
      "ewma": -1.1,
      "samples": 2,
      "wins": 0,
      "losses": 2,
      "sumR": -2.2
    },
    "rsi_bull": {
      "ewma": 1.3569999999999998,
      "samples": 5,
      "wins": 3,
      "losses": 2,
      "sumR": 3.4999999999999996
    },
    "head_shoulders": {
      "ewma": 1.3023038226441088,
      "samples": 3,
      "wins": 1,
      "losses": 2,
      "sumR": -0.33419281155048286
    },
    "inverse_hs": {
      "ewma": 0.9822896563190827,
      "samples": 3,
      "wins": 2,
      "losses": 1,
      "sumR": 0.8062969259253391
    },
    "inside_up": {
      "ewma": -1.1,
      "samples": 1,
      "wins": 0,
      "losses": 1,
      "sumR": -1.1
    },
    "three_soldiers": {
      "ewma": -1.1,
      "samples": 1,
      "wins": 0,
      "losses": 1,
      "sumR": -1.1
    },
    "range_down": {
      "ewma": 0.18819673637804693,
      "samples": 5,
      "wins": 2,
      "losses": 3,
      "sumR": -1.9356002600329176
    },
    "hammer": {
      "ewma": -1.1,
      "samples": 1,
      "wins": 0,
      "losses": 1,
      "sumR": -1.1
    },
    "bull_pennant": {
      "ewma": -0.8665014607301041,
      "samples": 2,
      "wins": 1,
      "losses": 1,
      "sumR": 0.13498539269895948
    },
    "bat_bull": {
      "ewma": -1.1,
      "samples": 1,
      "wins": 0,
      "losses": 1,
      "sumR": -1.1
    },
    "butterfly_bull": {
      "ewma": -1.1,
      "samples": 2,
      "wins": 0,
      "losses": 2,
      "sumR": -2.2
    },
    "channel_up": {
      "ewma": -1.1,
      "samples": 1,
      "wins": 0,
      "losses": 1,
      "sumR": -1.1
    },
    "rsi_bear": {
      "ewma": -1.1,
      "samples": 1,
      "wins": 0,
      "losses": 1,
      "sumR": -1.1
    },
    "three_crows": {
      "ewma": 1.5999999999999999,
      "samples": 4,
      "wins": 3,
      "losses": 1,
      "sumR": 4.6
    },
    "bear_flag": {
      "ewma": -1.1,
      "samples": 2,
      "wins": 0,
      "losses": 2,
      "sumR": -2.2
    },
    "rounding_top": {
      "ewma": 0.4653131470341566,
      "samples": 2,
      "wins": 1,
      "losses": 1,
      "sumR": -0.46076316996204836
    },
    "inside_down": {
      "ewma": 0.73440163,
      "samples": 9,
      "wins": 3,
      "losses": 6,
      "sumR": -0.9000000000000008
    },
    "rising_wedge": {
      "ewma": -1.1,
      "samples": 1,
      "wins": 0,
      "losses": 1,
      "sumR": -1.1
    }
  },
  "open": [],
  "history": []
};
