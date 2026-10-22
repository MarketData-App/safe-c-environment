"""Task 18b (Amendment C): SOFR rate and per-expiry carry-implied dividend yields of owner-chain local runs. Synthetic
chains only; the owner chain never enters a test."""
import datetime, hashlib, json, math, tempfile, unittest, unittest.mock
from pathlib import Path
from optionlab import market
from optionlab.params import CASE
from optionlab import protocol
R=0.0435;U=1791374400
CASE_FILE=Path('/src/examples/option-pricing-benchmark/benchmarks/project/cases/option-chain-greeks.json')

def chain_with(q,T=30/365,S=500.0,strikes=(480.0,485.0,490.0,495.0,500.0),updated=U):
    from optionlab.models import bsm_price
    c={k:[] for k in ('side','S','K','T','bid','ask','expiration','updated')}
    for k in strikes:
        for s in (0,1):
            p=bsm_price(s,S,k,T,R,q,0.2)
            for key,v in (('side',s),('S',S),('K',k),('T',T),('bid',p-0.01),('ask',p+0.01),('expiration',float(updated+round(T*31536000))),('updated',float(updated))):c[key].append(v)
    c['n']=len(c['side']);return c

def join(a,b):return {k:(a[k]+b[k]) for k in a}

def rate_info(**kw):
    return dict({'effective_date':'2026-10-07','percent_rate':4.33,'continuous_rate':R,'updated_other_date':0,'snapshot_date':'2026-10-07'},**kw)

class PairTests(unittest.TestCase):
    def test_parity_recovers_a_known_q_on_the_k_le_f_side(self):
        for q in (0.0,0.012,0.03):
            t=market.estimate(chain_with(q),R);(row,)=t.values()
            with self.subTest(q=q):self.assertEqual(row['method'],'parity-median');self.assertGreaterEqual(row['pairs'],3);self.assertLess(abs(row['q']-q),1e-6)
    def test_strikes_above_the_forward_are_excluded(self):
        p,_=market.pairs(chain_with(0.012,strikes=(500.0,505.0,510.0,515.0)),R)
        F=500.0*math.exp(R*30/365);self.assertTrue(all(K<=F for v in p.values() for K,*_ in v))
    def test_pair_rows_must_share_updated_and_spot(self):
        c=chain_with(0.012);c['updated'][1]+=60;c['S'][3]+=0.5
        p,skipped=market.pairs(c,R);self.assertEqual(skipped,2)
    def test_ineligible_rows_never_reach_the_estimator(self):
        for key,i,val in (('K',0,0.0),('S',2,-1.0),('bid',4,float('nan')),('T',6,float('nan')),('ask',8,0.0)):
            c=chain_with(0.012);c[key][i]=val
            with self.subTest(key=key):
                p,_=market.pairs(c,R);self.assertTrue(all(all(math.isfinite(x) for x in pair) for v in p.values() for pair in v))
                self.assertTrue(all(math.isfinite(r['q']) for r in market.estimate(c,R).values()))
    def test_pair_formula_and_invalid_argument(self):
        from optionlab.models import bsm_price
        S,K,T,q=500.0,495.0,0.25,0.012;C=bsm_price(0,S,K,T,R,q,0.2);P=bsm_price(1,S,K,T,R,q,0.2)
        self.assertLess(abs(market.q_from_pair(S,K,T,R,C,P)-q),1e-10);self.assertIsNone(market.q_from_pair(S,K,T,R,0.0,10*S))

class MissingQuoteTests(unittest.TestCase):
    """Task 18 owner-run fact: many rows are NO_BID. A pair needs an eligible, quotable call and put; the rest is counted."""
    def test_no_bid_rows_never_pair(self):
        for bid in (0.0,float('nan'),-0.01):
            c=chain_with(0.012);c['bid'][1]=bid;c['bid'][3]=bid                       # the puts of the two lowest strikes
            with self.subTest(bid=bid):
                p,skipped=market.pairs(c,R);self.assertEqual(skipped,0);self.assertEqual(sorted(K for v in p.values() for K,*_ in v),[490.0,495.0,500.0])
                (row,)=market.estimate(c,R).values();self.assertEqual((row['pairs'],row['method']),(3,'parity-median'))
    def test_skipped_and_dropped_are_counted_per_expiry(self):
        c=join(chain_with(0.012),chain_with(0.012,T=45/365));c['updated'][1]+=60
        t=market.estimate(c,R);rows=sorted(t.values(),key=lambda r:r['t_years'])
        self.assertEqual([r['skipped'] for r in rows],[1,0]);self.assertEqual([r['pairs'] for r in rows],[4,5])
        self.assertEqual(sum(r['skipped'] for r in rows),market.pairs(c,R)[1])
        bad=chain_with(0.012);bad['bid'][0]=bad['ask'][0]=0.06;bad['bid'][1]=bad['ask'][1]=490.0   # C - P + K e^{-rT} < 0 (K e^{-rT} is about 478.3)
        (row,)=market.estimate(bad,R).values();self.assertEqual((row['dropped'],row['pairs']),(1,4))
    def test_unquotable_quotes_never_pair(self):
        c=chain_with(0.012);c['ask'][0]=c['bid'][0]+5.0                               # spread above max(0.05, 0.10 mid)
        p,_=market.pairs(c,R);self.assertNotIn(480.0,[K for v in p.values() for K,*_ in v])

class EstimateTests(unittest.TestCase):
    def test_expiry_time_is_the_median_pair_time(self):
        c=chain_with(0.012);(row,)=market.estimate(c,R).values();self.assertEqual(row['t_years'],30/365)
    def test_fallbacks_and_flags(self):
        few=chain_with(0.012,strikes=(495.0,500.0));long_=chain_with(0.012,T=60/365,updated=U)
        short,lng=sorted(market.estimate(join(few,long_),R).values(),key=lambda r:r['t_years'])
        self.assertEqual((short['method'],lng['method']),('nearest','parity-median'));self.assertEqual(short['q'],lng['q'])
        self.assertEqual(next(iter(market.estimate(chain_with(0.012,T=3/365),R).values()))['method'],'assumption')
        hi=next(iter(market.estimate(chain_with(0.3,T=10/365),R).values()))
        self.assertEqual((hi['method'],hi['ex_dividend_suspect'],hi['rejected_bounds']),('assumption',True,1))
    def test_ex_dividend_neighbours_are_the_nearest_estimates_on_each_side(self):
        """Review Minor 3: an expiry without an estimate between two is passed over; both sides use the nearest estimate."""
        def chain(far_q):
            a=chain_with(0.012,T=8/365);b=chain_with(0.10,T=15/365);gap=chain_with(0.012,T=22/365,strikes=(495.0,500.0));d=chain_with(far_q,T=29/365)
            return join(join(a,b),join(gap,d))
        for far_q,flag in ((0.08,False),(0.012,True)):
            rows=sorted(market.estimate(chain(far_q),R).values(),key=lambda r:r['t_years'])
            with self.subTest(far_q=far_q):
                self.assertEqual([r['method'] for r in rows],['parity-median','parity-median','nearest','parity-median'])
                self.assertEqual(rows[1]['ex_dividend_suspect'],flag)
    def test_table_json_round_trip_keeps_float_expirations(self):
        t=market.estimate(join(chain_with(0.012),chain_with(0.02,T=45/365)),R)
        back=market.table_from_json(json.loads(json.dumps(market.table_json(t))))
        self.assertEqual(back,{e:r['q'] for e,r in t.items()})
        c=chain_with(0.012);self.assertEqual(back[c['expiration'][0]],t[c['expiration'][0]]['q'])
    def test_public_block_is_rounded(self):
        t=market.estimate(chain_with(0.012),R);pub=market.public(t,market.exercise_bias(chain_with(0.012),R,t,CASE),rate_info())
        e=pub['expiries'][0];self.assertEqual(e['q'],round(e['q'],6));self.assertEqual(e['t_years'],round(e['t_years'],4));self.assertFalse(pub['domain_qualified'])

class PublicPrivacyTests(unittest.TestCase):
    """Controller rule (Task 18 concern 2, Task 18b item 3): a value computed from fewer than 5 pairs is near-individual; the
    public block keeps its counts and method and withholds the value (null)."""
    def public(self,c):
        t=market.estimate(c,R);return t,market.public(t,market.exercise_bias(c,R,t,CASE),rate_info())
    def test_values_over_fewer_than_five_pairs_are_withheld(self):
        t,pub=self.public(chain_with(0.012,strikes=(490.0,495.0,500.0)));(e,)=pub['expiries']
        self.assertEqual((e['method'],e['pairs']),('parity-median',3))
        self.assertEqual([e[k] for k in ('q','mad','bias_median','bias_max','premium_spread_median')],[None]*5);self.assertEqual(e['bias_pairs'],3)
        self.assertIsNotNone(next(iter(t.values()))['q'])                              # the run still prices with it
    def test_nearest_of_a_withheld_estimate_is_withheld(self):
        few=chain_with(0.012,strikes=(495.0,500.0));four=chain_with(0.012,T=60/365,strikes=(485.0,490.0,495.0,500.0))
        _,pub=self.public(join(few,four));near,est=pub['expiries']
        self.assertEqual((near['method'],est['method'],est['pairs']),('nearest','parity-median',4));self.assertIsNone(near['q']);self.assertIsNone(est['q'])
    def test_five_pairs_publish_rounded_values_and_nearest_copies_them(self):
        few=chain_with(0.012,strikes=(495.0,500.0));five=chain_with(0.012,T=60/365)
        _,pub=self.public(join(few,five));near,est=pub['expiries']
        self.assertEqual(est['pairs'],5);self.assertIsNotNone(est['q']);self.assertEqual(near['q'],est['q'])
        for k in ('mad','bias_median','bias_max','premium_spread_median'):
            with self.subTest(k=k):self.assertIsNotNone(est[k]);self.assertEqual(est[k],round(est[k],6))
        self.assertEqual((est['bias_pairs'],near['bias_pairs']),(5,2))     # review Minor 1: the gate checks the bias count
        self.assertIsNone(near['mad']);self.assertEqual(near['pairs'],2)
    def test_assumption_and_dates_and_order(self):
        _,pub=self.public(chain_with(0.012,T=3/365));(e,)=pub['expiries']
        self.assertEqual((e['method'],e['q']),('assumption',market.ASSUMED_Q));self.assertTrue(pub['assumption_used'])
        self.assertRegex(e['expiration_date'],r'^\d{4}-\d{2}-\d{2}$');self.assertGreater(e['t_years'],0.0)
        _,pub=self.public(join(chain_with(0.012,T=60/365),chain_with(0.012)))
        self.assertEqual([x['expiration_date'] for x in pub['expiries']],sorted(x['expiration_date'] for x in pub['expiries']))
        self.assertEqual(pub['rate'],rate_info())
    def test_public_holds_no_quote(self):
        c=chain_with(0.012);_,pub=self.public(c)
        values={v for e in pub['expiries'] for v in e.values() if isinstance(v,float)}
        for x in c['bid']+c['ask']+c['K']+c['S']:
            with self.subTest(x=x):self.assertNotIn(x,values)
    def test_more_than_64_expiries_are_refused(self):
        t={float(U+86400*(i+1)):{'t_years':(i+1)/365,'pairs':0,'dropped':0,'skipped':0,'mad':None,'rejected_bounds':0,'q':0.012,'method':'assumption',
                                 'ex_dividend_suspect':False,'source':None} for i in range(65)}
        with self.assertRaises(ValueError):market.public(t,{},rate_info())

class BiasAndDateTests(unittest.TestCase):
    def test_american_bias_is_upward_and_a_lower_bound_label(self):
        c=chain_with(0.012);t=market.estimate(c,R);(row,)=market.exercise_bias(c,R,t,CASE).values()
        self.assertGreaterEqual(row['bias_median'],0.0);self.assertGreaterEqual(row['bias_max'],row['bias_median'])
    def test_snapshot_uses_the_new_york_date_and_business_rule(self):
        c=chain_with(0.012,updated=datetime.datetime(2026,10,8,1,30,tzinfo=datetime.timezone.utc).timestamp())
        self.assertEqual(market.snapshot(c),(datetime.date(2026,10,7),0))
        self.assertEqual(market.expected_effective(datetime.date(2026,10,12)),datetime.date(2026,10,9))
    def test_snapshot_counts_rows_of_another_date(self):
        c=chain_with(0.012);c['updated'][0]-=2*86400;c['updated'][1]=float('nan')
        self.assertEqual(market.snapshot(c)[1],1)
        with self.assertRaises(ValueError):market.expected_effective(datetime.date(2031,1,2))
    def test_rows_carry_per_expiry_q(self):
        from optionlab.contract import rows
        c=chain_with(0.012);e=c['expiration'][0]
        self.assertTrue(all(r[6]==R and r[7]==0.02 for r in rows(c,CASE,market={'rate':R,'q':{e:0.02}})))
        self.assertTrue(all(r[7]==CASE.dividend_yield for r in rows(c,CASE)))
    def test_rows_without_a_table_entry(self):
        from optionlab.contract import rows
        c=join(chain_with(0.012),chain_with(0.012,T=45/365));e=c['expiration'][0]
        with self.assertRaises(ValueError):rows(c,CASE,market={'rate':R,'q':{e:0.02}})      # an eligible row needs its expiry's q
        c['bid'][10:]=[0.0]*10                                                              # NO_BID rows: status order 3 decides them
        self.assertEqual({r[7] for r in rows(c,CASE,market={'rate':R,'q':{e:0.02}})},{0.02,market.ASSUMED_Q})

# The Federal Reserve holidays, SIFMA closures and supported years of the removed framework step tools/bench_market.py (commit 34512cd,
# Task 18a), frozen here as the independent reference of the example calendar. Source: https://www.federalreserve.gov/aboutthefed/k8.htm
FW_FED_HOLIDAYS=frozenset({
    '2025-01-01','2025-01-20','2025-02-17','2025-05-26','2025-06-19','2025-07-04','2025-09-01','2025-10-13','2025-11-11','2025-11-27','2025-12-25',
    '2026-01-01','2026-01-19','2026-02-16','2026-05-25','2026-06-19','2026-07-04','2026-09-07','2026-10-12','2026-11-11','2026-11-26','2026-12-25',
    '2027-01-01','2027-01-18','2027-02-15','2027-05-31','2027-06-19','2027-07-05','2027-09-06','2027-10-11','2027-11-11','2027-11-25','2027-12-25'})

def fw_business_date(day):
    """The removed framework rule, written again for this test: the day when it is a business day, else the previous business day."""
    if day.year not in (2025,2026,2027):raise ValueError('year')
    while day.weekday()>=5 or day.isoformat() in FW_FED_HOLIDAYS:
        day-=datetime.timedelta(days=1)
        if day.year not in (2025,2026,2027):raise ValueError('year')
    return day

class HolidayCalendarTests(unittest.TestCase):
    """Property (was HolidayAgreementTests, which compared the example with the framework file tools/bench_market.py; FR3 removed
    that file, so the framework counterpart is a frozen copy of its calendar): the example's SOFR business-date rule keeps the holiday
    lists, the SIFMA closures, the supported years and the New York date of the removed Task 18a rule."""
    def test_lists_are_the_frozen_framework_lists(self):
        self.assertEqual(market.FED_HOLIDAYS,FW_FED_HOLIDAYS);self.assertEqual(market.SIFMA_CLOSURES,frozenset());self.assertEqual(market.SUPPORTED_YEARS,(2025,2026,2027))
    def test_business_dates_agree_on_every_supported_day(self):
        day=datetime.date(min(market.SUPPORTED_YEARS),1,1);end=datetime.date(max(market.SUPPORTED_YEARS),12,31)
        while day<=end:
            try:want=fw_business_date(day)
            except ValueError:want=None
            try:got=market.expected_effective(day)
            except ValueError:got=None
            self.assertEqual(got,want,day.isoformat());day+=datetime.timedelta(days=1)
    def test_the_protocol_sofr_day_is_a_business_day(self):
        day=datetime.date.fromisoformat(protocol.sofr()['day']);self.assertEqual(market.expected_effective(day),day)
        self.assertEqual(market.expected_effective(datetime.date(2026,10,12)),datetime.date(2026,10,9))     # Columbus Day: the Friday before
    def test_new_york_date_changes_at_the_two_time_changes(self):
        """Midnight New York time before and after each change: EDT (UTC-4) from 2026-03-08 07:00 UTC, EST (UTC-5) from 2026-11-01 06:00 UTC."""
        d=datetime.date
        for utc,want in (('2026-03-08T04:59:59',d(2026,3,7)),('2026-03-08T05:00:00',d(2026,3,8)),     # EST, before the change
                         ('2026-03-09T03:59:59',d(2026,3,8)),('2026-03-09T04:00:00',d(2026,3,9)),     # EDT, after it
                         ('2026-11-01T03:59:59',d(2026,10,31)),('2026-11-01T04:00:00',d(2026,11,1)),  # EDT, before the change
                         ('2026-11-02T04:59:59',d(2026,11,1)),('2026-11-02T05:00:00',d(2026,11,2))):  # EST, after it
            e=datetime.datetime.fromisoformat(utc).replace(tzinfo=datetime.timezone.utc).timestamp()
            with self.subTest(utc=utc):self.assertEqual(market.new_york_date(e),want)
    def test_new_york_date_agrees_with_the_zone_database_hourly(self):
        try:
            from zoneinfo import ZoneInfo
            ny=ZoneInfo('America/New_York');ny.utcoffset(datetime.datetime(2026,1,1))
        except Exception as error:
            self.skipTest('no time zone database: '+type(error).__name__)
        start=int(datetime.datetime(2025,1,1,tzinfo=datetime.timezone.utc).timestamp())
        for k in range(0,3*366*24):
            e=start+k*3600+1799
            self.assertEqual(market.new_york_date(e),datetime.datetime.fromtimestamp(e,ny).date())

class LocalDomainSpotCheckTests(unittest.TestCase):
    """Amendment C item 5: the oracle edge rows gain local-domain spot checks (label "local-domain spot check"); each model, an
    at-the-money put, T = 30 days, at b = -0.10, b = +0.09 and q = -0.02. They are judged like every edge row."""
    def test_fixture_holds_the_generated_spot_check_rows(self):
        from optionlab import oracle_gen
        from optionlab.reference import evaluate
        fx=protocol.oracle()
        rows=[e for e in fx['oracle']['edge_rows'] if e['name'].startswith('local-domain-')]
        self.assertEqual(sorted(e['name'] for e in rows),sorted(f'local-domain-{m}-{t}' for m in ('bsm','bjs','crr') for t in ('b-m010','b-p009','q-m002')))
        self.assertEqual(rows,oracle_gen.local_domain_rows(CASE))
        for e in rows:
            side,S,K,T,bid,ask,r,q=e['row']
            with self.subTest(name=e['name']):
                self.assertEqual((side,S,K,T,r,e['status']),(1,100.0,100.0,30/365,CASE.rate,'OK'))
                self.assertIn(round(r-q,10),(-0.10,0.09,round(CASE.rate+0.02,10)))
                self.assertEqual(evaluate(tuple(e['row']),e['model'],CASE)[0],'OK')

def local_sample(n=64,seed=11,days=1):
    """(adapter, dataset ref, chain) of a synthetic dataset relabeled as a local one (synthetic.as_local_sample); no owner row."""
    from benchlab.workload import load_case_adapter
    from optionlab import synthetic
    a=load_case_adapter(json.loads(CASE_FILE.read_text()))
    data=synthetic.as_local_sample(a.synthesize(n,seed),days);p=Path(tempfile.mkdtemp())/'dataset.json';p.write_bytes(data)
    return a,{'path':str(p),'sha256':hashlib.sha256(data).hexdigest()}

PAIR_Q=0.03     # the carry yield planted in the pair rows of pair_sample; it differs from CASE.dividend_yield (0.012)

def pair_sample(n=64,seed=11,q=PAIR_Q):
    """(adapter, dataset ref, expiration) of a local-like dataset that holds call-put pairs (T11T12-A01): the first ten rows of
    local_sample become five call-put pairs of one expiry (37 days, a tenor the generator never uses; spot 500, strikes 480 to 500, mids priced with the protocol
    rate and `q`, quotes 0.02 wide), so the parity estimate exists for that expiry. Every other row stays a relabeled
    synthetic row. Synthetic data in, synthetic data out."""
    from optionlab.models import bsm_price
    a,ds=local_sample(n,seed);obj=json.loads(Path(ds['path']).read_bytes());r=market.protocol_rate()['continuous_rate']
    up=max(obj['updated']);T=37/365;e=up+round(T*31536000);S=500.0
    for j,(k,side) in enumerate((k,s) for k in (480.0,485.0,490.0,495.0,500.0) for s in (0,1)):
        p=bsm_price(side,S,k,(e-up)/31536000,r,q,0.2)
        for key,v in (('side','put' if side else 'call'),('strike',k),('expiration',e),('updated',up),('underlyingPrice',S),('bid',p-0.01),('ask',p+0.01),('mid',p)):obj[key][j]=v
    data=json.dumps(obj).encode();path=Path(tempfile.mkdtemp())/'pairs.json';path.write_bytes(data)
    return a,{'path':str(path),'sha256':hashlib.sha256(data).hexdigest()},float(e)

class ProtocolRateTests(unittest.TestCase):
    """EX-6, T10-A05: the market rate is the protocol constant, converted; nothing else supplies it."""
    def test_the_model_rate_is_the_continuous_act365_rate_of_the_percent(self):
        s=protocol.sofr();rec=market.protocol_rate()
        self.assertEqual((s['day'],s['percent'],s['rate']),('2026-10-05',3.89,0.0389))
        self.assertEqual(rec,{'effective_date':'2026-10-05','percent_rate':3.89,'continuous_rate':365*math.log1p(3.89/100/360)})
        self.assertLess(abs(rec['continuous_rate']-0.0394381),5e-8);self.assertNotEqual(rec['continuous_rate'],s['rate'])   # not the protocol `rate` field
        self.assertEqual(market.continuous_rate(0.0),0.0)
    def test_the_rate_comes_from_the_protocol_only(self):
        """No environment variable, argument or other file reaches the rate; the example source of the market step holds no network call."""
        import os
        for name in ('SOFR','MARKET_RATE','SAFE_C_MARKET','RISK_FREE_RATE','OPTIONLAB_RATE'):
            with self.subTest(name=name),unittest.mock.patch.dict(os.environ,{name:'9.99'}):self.assertEqual(market.protocol_rate()['percent_rate'],3.89)
        root=Path(market.__file__).parent
        for name in ('market.py','adapter.py'):
            src=(root/name).read_text()
            for word in ('os.environ','os.getenv','urllib','socket','http.client','requests','ssl'):
                with self.subTest(module=name,word=word):self.assertNotIn(word,src)
        import inspect
        self.assertEqual(list(inspect.signature(market.protocol_rate).parameters),[]);self.assertEqual(list(inspect.signature(self.adapter().with_market).parameters),['items'])
    def adapter(self):
        from benchlab.workload import load_case_adapter
        return load_case_adapter(json.loads(CASE_FILE.read_text()))

class OwnerChainFailClosedTests(unittest.TestCase):
    """T9-A04 (the property of the removed case key local_requires ["market"]): a local dataset uses the protocol rate and the q table
    of the market step; the adapter refuses to fall back to the case assumption rates or to run without a rate."""
    def test_a_synthetic_dataset_keeps_the_labeled_assumptions(self):
        a=self.adapter();data=a.synthesize(16,11);p=Path(tempfile.mkdtemp())/'d.json';p.write_bytes(data)
        chain=a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()})
        self.assertEqual((set(chain['r']),set(chain['q'])),({CASE.rate},{CASE.dividend_yield}))
    def test_every_synthetic_symbol_carries_the_label(self):
        from optionlab.contract import decode_chain_origin
        data=self.adapter().synthesize(40,3);self.assertTrue(decode_chain_origin(data)[1])
        obj=json.loads(data);obj['optionSymbol'][5]='SPY'+obj['optionSymbol'][5][3:];self.assertFalse(decode_chain_origin(json.dumps(obj).encode())[1])
        empty={k:([] if isinstance(v,list) else v) for k,v in json.loads(data).items()};chain,synthetic=decode_chain_origin(json.dumps(empty).encode())
        self.assertEqual((chain['n'],synthetic),(0,False))      # an empty dataset is not labeled synthetic
    def test_a_symbol_of_another_form_or_underlying_takes_the_owner_path(self):
        """T11T12-A03: synthetic means the exact generator form SYN + expiration digits + C/P + 5 strike digits and underlying SYN on
        every row. A SYNA-style OCC root, a mixed dataset, a wrong underlying or a malformed tail is not synthetic."""
        from optionlab.contract import decode_chain_origin
        data=self.adapter().synthesize(40,3);base=json.loads(data);self.assertTrue(decode_chain_origin(data)[1])
        def flag(mutate):
            obj=json.loads(data);mutate(obj);return decode_chain_origin(json.dumps(obj).encode())[1]
        def symbol(i,text):
            def m(obj):obj['optionSymbol'][i]=text
            return m
        tail=base['optionSymbol'][7][3:]
        for name,mutate in (('SYNA root',symbol(7,'SYNA'+tail)),('mixed dataset',symbol(7,'SPY'+tail)),('no side letter',symbol(7,'SYN'+tail.replace('C','').replace('P',''))),
                            ('short strike',symbol(7,base['optionSymbol'][7][:-1])),('long strike',symbol(7,base['optionSymbol'][7]+'0')),('lowercase side',symbol(7,'SYN'+tail.lower())),
                            ('no expiration',symbol(7,'SYN'+tail[-6:])),('trailing space',symbol(7,base['optionSymbol'][7]+' ')),
                            ('underlying SPY',lambda obj:obj['underlying'].__setitem__(7,'SPY')),('underlying SYNA',lambda obj:obj['underlying'].__setitem__(7,'SYNA')),
                            ('underlying null',lambda obj:obj['underlying'].__setitem__(7,None))):
            with self.subTest(name=name):self.assertFalse(flag(mutate))
        def all_syna(obj):obj['optionSymbol']=['SYNA'+s[3:] for s in obj['optionSymbol']]
        self.assertFalse(flag(all_syna))
        def no_underlying(obj):del obj['underlying']
        self.assertFalse(flag(no_underlying))
    def test_a_syna_style_dataset_takes_the_protocol_rate_not_the_case_assumptions(self):
        """T11T12-A03 through the adapter: the case assumptions never reach a dataset whose symbols only start with SYN (the rows are
        the local sample on the protocol day, with a SYNA root)."""
        a,ds=local_sample(16);obj=json.loads(Path(ds['path']).read_bytes());obj['optionSymbol']=['SYNA'+s[3:] for s in obj['optionSymbol']]
        data=json.dumps(obj).encode();p=Path(tempfile.mkdtemp())/'syna.json';p.write_bytes(data)
        chain=a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()})
        self.assertEqual(set(chain['r']),{market.protocol_rate()['continuous_rate']});self.assertNotEqual(set(chain['r']),{CASE.rate})
    def test_the_panel_inputs_refuse_a_chain_that_is_not_synthetic(self):
        """T11T12-A04 (G3.3): load marks the origin of the chain; panel_inputs takes a synthetic chain only. An owner chain and a chain
        without the mark are refused before any pricing."""
        a=self.adapter();data=a.synthesize(16,11);p=Path(tempfile.mkdtemp())/'d.json';p.write_bytes(data)
        chain=a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()});self.assertIs(chain['synthetic'],True)
        self.assertIs(a.slice(chain,8)['synthetic'],True)
        owner,ods,_=pair_sample();oc=owner.load(ods);self.assertIs(oc['synthetic'],False)
        for name,c in (('owner chain',oc),('no mark',{k:v for k,v in chain.items() if k!='synthetic'}),('marked false',{**chain,'synthetic':False})):
            with self.subTest(name=name),self.assertRaises(ValueError) as e:a.panel_inputs(c,1)
            self.assertEqual(str(e.exception),'panel inputs are synthetic only (G3.3)')
        # T11T12R1-A03: the guard lets a chain that load marked synthetic through, and panel_inputs returns its panel inputs
        from optionlab import panel
        with self.subTest(name='loaded synthetic chain'):
            got=a.panel_inputs(chain,1)
            self.assertEqual((got['n'],got['models']),(16,list(panel.PANEL_MODELS)))
            self.assertRegex(got['reference_sha256'],'^[0-9a-f]{64}$')
            self.assertEqual(json.dumps(got,sort_keys=True),json.dumps(panel.inputs(chain,a.params,1),sort_keys=True))
    def test_a_local_dataset_takes_the_protocol_rate_and_the_market_q(self):
        a,ds,e=pair_sample();chain=a.load(ds);rate=market.protocol_rate()['continuous_rate']
        self.assertEqual(set(chain['r']),{rate});self.assertNotEqual(rate,CASE.rate)
        est=market.estimate(chain,rate);table={x:r['q'] for x,r in est.items()}
        for i in range(chain['n']):
            if market.eligible(chain,i):self.assertEqual(chain['q'][i],table[chain['expiration'][i]])
        # T11T12-A01: the dataset holds call-put pairs in one expiry, so that expiry takes the estimate and never the case q
        self.assertEqual(est[e]['method'],'parity-median');self.assertGreaterEqual(est[e]['pairs'],market.MIN_PAIRS)
        self.assertNotEqual(est[e]['q'],CASE.dividend_yield);self.assertLess(abs(est[e]['q']-PAIR_Q),1e-6)
        rows_e=[i for i in range(chain['n']) if chain['expiration'][i]==e];self.assertEqual(len(rows_e),10)
        self.assertEqual({chain['q'][i] for i in rows_e},{est[e]['q']})
        self.assertNotEqual(chain['q'],[CASE.dividend_yield]*chain['n'])
        ref=a.reference(chain);base=a.reference(a.load(self.synthetic_ref(a)))
        self.assertNotEqual(a.digest(ref),a.digest(base))
        res=a.materialize(a.run(a.prepare(chain,'py-reference'),'py-reference',1));self.assertTrue(a.validate(res,ref,chain)['eligible'])
    def test_a_local_dataset_without_pairs_takes_the_labeled_q_for_its_expiries(self):
        """The counterpart of the pair case: a 64-row sample holds no call-put pair, so each expiry takes the labeled q (method `assumption`)."""
        a,ds=local_sample();chain=a.load(ds);rate=market.protocol_rate()['continuous_rate']
        self.assertEqual({r['method'] for r in market.estimate(chain,rate).values()},{'assumption'})
    def synthetic_ref(self,a):
        data=a.synthesize(64,11);p=Path(tempfile.mkdtemp())/'s.json';p.write_bytes(data);return {'path':str(p),'sha256':hashlib.sha256(data).hexdigest()}
    def test_a_local_dataset_of_another_snapshot_day_stops_the_run(self):
        for days in (0,2,5):
            a,ds=local_sample(days=days)
            with self.subTest(days=days),self.assertRaises(ValueError) as e:a.load(ds)
            self.assertTrue(str(e.exception).startswith('market_date_mismatch'))
    def test_a_local_dataset_without_a_finite_updated_time_stops_the_run(self):
        a,ds=local_sample(8)
        obj=json.loads(Path(ds['path']).read_bytes());obj['updated']=[None]*len(obj['updated']);data=json.dumps(obj).encode();p=Path(ds['path']);p.write_bytes(data)
        with self.assertRaises(ValueError):a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()})
    def test_the_error_messages_hold_no_record_value(self):
        a,ds=local_sample(days=3)
        with self.assertRaises(ValueError) as e:a.load(ds)
        raw=json.loads(Path(ds['path']).read_bytes());text=str(e.exception)
        self.assertEqual(text,'market_date_mismatch: the protocol SOFR day is not the SOFR date of the dataset snapshot')
        self.assertFalse(any(str(v) in text for k in ('bid','ask','strike','underlyingPrice') for v in raw[k][:8]))
    def test_the_market_step_needs_no_network_and_prints_nothing(self):
        """The load of a local dataset (the market step) runs with sockets refused and writes nothing to stdout or stderr."""
        import contextlib, io, socket
        a,ds=local_sample()
        def refuse(*args,**kw):raise AssertionError('network access')
        out=io.StringIO();err=io.StringIO()
        with unittest.mock.patch.object(socket.socket,'connect',refuse),unittest.mock.patch.object(socket,'getaddrinfo',refuse),contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            a.load(ds);a.market_parameters(a.load(ds))
        self.assertEqual((out.getvalue(),err.getvalue()),('',''))
    def test_the_public_block_of_a_local_dataset_holds_no_quote(self):
        """market_parameters (the unused market block) keeps the privacy rule on a local-like dataset with an estimated q: the
        estimate is published (five pairs) and no quote or strike value is."""
        a,ds,e=pair_sample(128);chain=a.load(ds);m=a.market_parameters(chain);self.assertTrue(m['date_ok'])
        est=market.estimate(chain,market.protocol_rate()['continuous_rate'])[e]
        self.assertEqual((est['method'],est['pairs']),('parity-median',5));self.assertNotEqual(est['q'],CASE.dividend_yield)
        values={v for x in m['public']['expiries'] for v in x.values() if isinstance(v,float)}
        self.assertIn(round(est['q'],6),values)                  # the public block holds the estimate, so the quote test is not vacuous
        # a quote of exactly 0.0 is the no-bid marker of the sample, not a price; the rounded statistics (mad of identical pair yields) are 0.0 too
        for x in chain['bid']+chain['ask']+chain['K']+chain['S']:
            if x!=0.0:self.assertNotIn(x,values)
    def adapter(self):
        from benchlab.workload import load_case_adapter
        return load_case_adapter(json.loads(CASE_FILE.read_text()))

class AdapterMarketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a,cls.ds=local_sample(64);cls.chain=cls.a.load(cls.ds)
        day,_=market.snapshot(cls.chain);cls.expected=market.expected_effective(day).isoformat()
    def test_market_parameters_on_the_protocol_date(self):
        m=self.a.market_parameters(self.chain)
        self.assertEqual(set(m),{'public','table','rate','date_ok'});self.assertTrue(m['date_ok']);self.assertEqual(m['rate'],market.protocol_rate()['continuous_rate'])
        self.assertEqual(self.expected,protocol.sofr()['day']);self.assertEqual(m['public']['rate']['effective_date'],self.expected);self.assertTrue(m['public']['expiries'])
        self.assertEqual(json.loads(json.dumps(m['table'])),m['table'])
    def test_market_parameters_refuse_another_date(self):
        a,ds=local_sample(days=2)
        from optionlab.contract import decode_chain_origin
        chain=decode_chain_origin(Path(ds['path']).read_bytes())[0]
        m=a.market_parameters(chain)
        self.assertFalse(m['date_ok']);self.assertEqual((m['table'],m['public']['expiries']),([],[]))
        self.assertEqual(m['public']['rate']['effective_date'],protocol.sofr()['day']);self.assertNotEqual(m['public']['rate']['snapshot_date'],protocol.sofr()['day'])
    def test_with_market_prices_every_row_with_its_expiry_q(self):
        """The py-reference side runs in this container now; the py-optimized prepare/run/validate under market rates (T11T12-A02)
        needs SciPy, so the test stays in the T14 list until SciPy enters. Counterpart of the per-row rate path: test_adapter
        PerRowRateTests."""
        m=self.a.market_parameters(self.chain);b=self.a.with_market(m['table'])
        table=market.table_from_json(m['table']);chain=b.load(self.ds)
        self.assertEqual(set(chain['r']),{m['rate']})
        for i in range(chain['n']):
            if market.eligible(chain,i):self.assertEqual(chain['q'][i],table[chain['expiration'][i]])
        prep=b.prepare(chain,'py-reference');self.assertEqual([r[7] for r in prep],chain['q']);self.assertEqual({r[6] for r in prep},{m['rate']})
        ref=b.reference(chain);base=self.a.reference(self.chain)
        self.assertEqual(b.digest(ref),self.a.digest(base))               # the owner-like load and the explicit table give the same pricing
        res=b.materialize(b.run(prep,'py-reference',1));self.assertTrue(b.validate(res,ref,chain)['eligible'])
        popt=b.prepare(chain,'py-optimized');self.assertEqual(list(popt['q']),chain['q'])      # T11T12-A02: py-optimized under market rates
        res=b.materialize(b.run(popt,'py-optimized',1));self.assertTrue(b.validate(res,ref,chain)['eligible'])

if __name__=='__main__':unittest.main()
