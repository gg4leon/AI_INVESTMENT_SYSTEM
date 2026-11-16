"""AIS v1.0 historical out-of-sample research tests.

Synthetic TEST FIXTURES only, no market fetch or real trading.
"""
import unittest
import numpy as np
import pandas as pd

from nory.validation import (
    ValidationConfig,validate_out_of_sample,_clean,_signal,STRATEGIES,
)


def prices(n=300):
    t=np.arange(n)
    # Two regimes; deterministic, nonstationary data prevents always-win assumptions.
    closes=100*np.exp(.0007*t+0.018*np.sin(t/8)+.012*np.cos(t/21))
    closes[n//2:]*=np.exp(-.002*np.arange(n-n//2))
    opens=closes*(1+.0006*np.cos(t/7))
    return pd.DataFrame({
        "Open":opens,"Close":closes,
    },index=pd.date_range("2024-01-01",periods=n,freq="D"))


class ValidationTests(unittest.TestCase):
    def test_calibration_uses_only_training_data(self):
        a=prices()
        b=a.copy()
        split=int(len(a)*.7)
        b.iloc[split:,-1]=b.iloc[split:,-1]*1.5
        b.iloc[split:,0]=b.iloc[split:,0]*1.5
        ra=validate_out_of_sample(a)
        rb=validate_out_of_sample(b)
        self.assertEqual(ra["chosen_from_train_only"],rb["chosen_from_train_only"])
        self.assertEqual(ra["all_training_summaries"],rb["all_training_summaries"])
        self.assertEqual(ra["holdout_size"],len(a)-split)
        self.assertNotEqual(ra["benchmark_100pct_buy_hold_net_pct"],
                            rb["benchmark_100pct_buy_hold_net_pct"])

    def test_previous_close_only_for_signal(self):
        df=prices()
        a=_clean(df)
        index=90
        signal=_signal(a,index,"TREND",False)
        altered=df.copy()
        altered.iloc[index,altered.columns.get_loc("Close")]*=3
        signal_b=_signal(_clean(altered),index,"TREND",False)
        self.assertEqual(signal,signal_b)

    def test_costs_lower_benchmark_and_not_guarantee_profit(self):
        a=prices()
        cheap=validate_out_of_sample(a,ValidationConfig(fee_bps_each_side=0.,
                                  slippage_bps_each_side=0.))
        costly=validate_out_of_sample(a,ValidationConfig(fee_bps_each_side=100.,
                                   slippage_bps_each_side=20.))
        self.assertGreater(cheap["benchmark_100pct_buy_hold_net_pct"],
                           costly["benchmark_100pct_buy_hold_net_pct"])
        self.assertEqual(set(cheap["holdout_results"]),set(STRATEGIES))
        self.assertEqual(costly["holdout_results"]["CASH"]["return_pct"],0.)

    def test_30pct_position_cap_and_long_only(self):
        a=validate_out_of_sample(prices())
        for record in a["holdout_results"].values():
            self.assertGreaterEqual(record["final_equity"],0.)
            self.assertLessEqual(record["buys"],len(prices()))
            self.assertGreaterEqual(record["max_drawdown_pct"],0.)
            self.assertTrue(all(tr["signal_used_from"]=="PRIOR_CLOSED_DAY"
                                for tr in record["trades"]))

    def test_invalid_inputs_rejected(self):
        with self.assertRaises(ValueError):
            validate_out_of_sample(prices(90))
        df=prices()
        df.loc[df.index[60],"Open"]=-1
        with self.assertRaises(ValueError):
            validate_out_of_sample(df)
        with self.assertRaises(ValueError):
            ValidationConfig(train_fraction=.99)
        with self.assertRaises(ValueError):
            ValidationConfig(fee_bps_each_side=-1)


if __name__=="__main__":
    unittest.main()
