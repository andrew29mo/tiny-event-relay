"""Synthetic fixtures test report arithmetic only; service behavior uses live processes."""
import copy
import hashlib
import unittest

from relay.service import canonical
from tools.benchmark import summarize,aggregate,render
from tools.check_report import check
from tools.evidence import source_manifest


def fixture():
    report = {"status":"passed","source":source_manifest(),"parameters":{"count":2,"rate":10,"repeats":1},
              "environment":{"platform":"synthetic fixture","python":"fixture"},"limitations":["<unsafe>"],"trials":[]}
    for scenario in ("normal","outage","restart"):
        for size in (256,16384):
            rows,effects,attempts = [],[],{}
            for i in range(2):
                body = canonical({"sequence":i,"blob":"x"*size})
                event_id = f"event-{i:05}"
                applied = .3+i*.01
                digest = hashlib.sha256(body).hexdigest()
                rows.append({"id":event_id,"status":202,"duplicate":False,"scheduled_s":i/10,"invoked_s":i/10,
                             "acknowledged_s":i/10+.001,"digest":digest,"canonical_bytes":len(body),"applied_s":applied,"delivery_attempts":1})
                effects.append({"id":event_id,"digest":digest,"transaction_recorded":applied-.001,"committed":applied})
                attempts[event_id] = 1
            t = {"scenario":scenario,"blob_bytes":size,"repeat":0,"count":2,"rate_per_s":10,"records":rows,
                 "relay_cli_args":["relay","serve","--timeout","0.3","--retry-base","0.05","--retry-cap","0.2"],
                 "samples":[{"elapsed_s":i*.01,"database_bytes":100,"wal_bytes":20,"shm_bytes":10,"relay_rss_bytes":1000,"pid":1} for i in range(3)],
                 "receiver_receipt":{"effects":effects,"attempts":attempts},"wall_start":0,"wall_clock_drift_s":0,
                 "resume_s":.2 if scenario!="normal" else None,"backlog_snapshot":{"states":{"pending":2}},
                 "final_snapshot":{"states":{"delivered":2},"retained_payload_bytes":0,"worker_error":None}}
            t["summary"] = summarize(t)
            report["trials"].append(t)
    report["aggregate"] = aggregate(report)
    return report


class ReportTests(unittest.TestCase):
    def test_consistent_fixture_and_html_escaping(self):
        report = fixture()
        check(report)
        rendered = render(report)
        self.assertIn("&lt;unsafe&gt;",rendered)
        self.assertNotIn("<unsafe>",rendered)

    def test_reject_changed_summary(self):
        report = fixture()
        report["trials"][0]["summary"]["unique_effects_per_s"] *= 10
        with self.assertRaisesRegex(ValueError,"summary"):
            check(report)

    def test_reject_missing_trial(self):
        report = fixture()
        report["trials"].pop()
        with self.assertRaisesRegex(ValueError,"coverage"):
            check(report)

    def test_reject_wrong_payload_receipt(self):
        report = fixture()
        report["trials"][0]["receiver_receipt"]["effects"][0]["digest"] = "0"*64
        with self.assertRaisesRegex(ValueError,"payload"):
            check(report)

    def test_reject_changed_arrival_schedule(self):
        report = fixture()
        report["trials"][0]["records"][0]["scheduled_s"] = .002
        with self.assertRaisesRegex(ValueError,"schedule"):
            check(report)

    def test_reject_duplicate_effect_even_with_valid_unique_ids(self):
        report = fixture()
        effects = report["trials"][0]["receiver_receipt"]["effects"]
        effects.append(copy.deepcopy(effects[0]))
        with self.assertRaisesRegex(ValueError,"duplicate"):
            check(report)

    def test_reject_failed_run_or_changed_source(self):
        report = fixture()
        report["status"] = "failed"
        with self.assertRaisesRegex(ValueError,"successfully"):
            check(report)
        report = fixture()
        report["source"]["sha256"] = "0"*64
        with self.assertRaisesRegex(ValueError,"source"):
            check(report)

    def test_require_post_commit_measurement(self):
        report = fixture()
        report["trials"][0]["receiver_receipt"]["effects"][0]["committed"] = None
        with self.assertRaisesRegex(ValueError,"post-commit"):
            check(report)
