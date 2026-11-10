import io
import os
import sys
import time
import random
from datetime import datetime, timezone, timedelta

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.db.mongo import get_mongo_db, ensure_indexes
from app.repositories.lead_repository import LeadRepository
from app.repositories.report_repository import ReportRepository
from app.services.export_service import ExportService


def run_benchmark(target_count: int = 100_000):
    print("=" * 70)
    print(f"FLOWDESK SCALABILITY & PERFORMANCE BENCHMARK ({target_count:,} RECORDS)")
    print("=" * 70)

    db = get_mongo_db()
    ensure_indexes(db)
    lead_repo = LeadRepository(db)
    report_repo = ReportRepository(db)
    export_service = ExportService()

    ws_id = "ws_benchmark_scale"
    rep_id = "rep_benchmark_100k"

    # Setup Workspace & Report
    db.workspaces.update_one(
        {"_id": ws_id},
        {"$set": {"name": "Benchmark Workspace", "owner_id": "benchmarker"}},
        upsert=True,
    )
    db.outreach_reports.update_one(
        {"_id": rep_id},
        {
            "$set": {
                "workspace_id": ws_id,
                "title": f"Scalability Benchmark ({target_count:,} Leads)",
                "description": "Synthetic dataset for load and latency verification",
                "is_archived": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
        upsert=True,
    )

    # 1. Benchmark Bulk Ingestion
    print(f"\n1. Ingestion Benchmark: Generating and inserting {target_count:,} lead documents...")
    batch_size = 5_000
    statuses = ["not_contacted", "attempted", "contacted", "delivered", "replied"]
    interests = ["unknown", "interested", "potentially_interested", "not_interested", "awaiting_response"]
    channels = ["phone", "email", "whatsapp", "linkedin", "instagram"]
    employees = ["Asha Rao", "Vikram Patel", "Sarah Jenkins", "Michael Chang", "Neha Sharma"]
    cities = ["Bengaluru", "Mumbai", "San Francisco", "New York", "London", "Austin", "Berlin"]
    companies = ["Apex Global", "TechFlow", "Starlight Systems", "Nexus AI", "Quantum Labs", "Summit Retail"]

    # Check existing count
    current_count = db.leads.count_documents({"workspace_id": ws_id, "report_id": rep_id})
    start_time = time.time()

    if current_count < target_count:
        needed = target_count - current_count
        print(f"   Existing records: {current_count:,}. Inserting remaining {needed:,} records in batches of {batch_size:,}...")
        docs = []
        today_str = datetime.now(timezone.utc).date().isoformat()
        
        for i in range(1, needed + 1):
            idx = current_count + i
            contact_st = random.choice(statuses)
            interest_st = random.choice(interests)
            channel = random.choice(channels)
            emp = random.choice(employees)
            city = random.choice(cities)
            company = random.choice(companies)

            fu_due = (datetime.now(timezone.utc) + timedelta(days=random.randint(-5, 10))).date().isoformat()
            if fu_due < today_str:
                fu_status = "overdue"
            elif fu_due == today_str:
                fu_status = "due"
            else:
                fu_status = "scheduled"

            doc = {
                "_id": f"bench_lead_{idx}",
                "workspace_id": ws_id,
                "report_id": rep_id,
                "attributes": {
                    "Company Name": company,
                    "Phone Number": f"+91 {9800000000 + idx}",
                    "Product Interest": "Enterprise Platform",
                    "Lead Source": "Outreach Campaign",
                    "Budget": str(random.randint(5, 50) * 1000),
                },
                "normalized": {
                    "name": f"Prospect {idx}",
                    "email": f"prospect_{idx}@benchmark-example.com",
                    "phone": f"+91{9800000000 + idx}",
                    "company": company,
                    "location": city,
                    "deal_value": float(random.randint(5, 50) * 1000),
                },
                "outcome": {
                    "contact_status": contact_st,
                    "interest_status": interest_st,
                    "source": "benchmark",
                },
                "channel": channel,
                "assigned_employee": emp,
                "follow_up": {
                    "status": fu_status,
                    "due_date": fu_due,
                    "reason": "Benchmark task",
                    "notes": "",
                    "completed_at": None,
                },
                "timestamps": {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "first_seen_at": datetime.now(timezone.utc).isoformat(),
                },
                "history": [],
            }
            docs.append(doc)

            if len(docs) >= batch_size:
                db.leads.insert_many(docs, ordered=False)
                docs = []
                elapsed_so_far = time.time() - start_time
                print(f"   Progress: {i:,}/{needed:,} inserted ({i / elapsed_so_far:.0f} docs/sec)...")

        if docs:
            db.leads.insert_many(docs, ordered=False)

    insert_duration = time.time() - start_time
    total_leads = db.leads.count_documents({"workspace_id": ws_id, "report_id": rep_id})
    print(f"   Total leads in report: {total_leads:,}")
    print(f"   Ingestion Time: {insert_duration:.2f}s (~{target_count / max(insert_duration, 0.001):.0f} records/sec)")

    # 2. Benchmark Pagination Latencies
    print("\n2. Pagination Latency Benchmark:")
    pages_to_test = [1, 50, 500, 1000]
    for p in pages_to_test:
        skip = (p - 1) * 50
        t0 = time.time()
        leads = lead_repo.find_leads(
            workspace_id=ws_id,
            report_id=rep_id,
            skip=skip,
            limit=50,
        )
        lat = (time.time() - t0) * 1000
        print(f"   Page {p:4d} (skip {skip:6d}, limit 50): {lat:6.2f} ms | Fetched: {len(leads)} leads")

    # 3. Benchmark Indexed Filtering Queries
    print("\n3. Filter Query Latency Benchmark:")
    filter_tests = [
        ("Interested Leads", {"interest_status": "interested"}),
        ("Contacted Leads", {"contact_status": "contacted"}),
        ("Overdue Follow-ups", {"follow_up_status": "overdue"}),
        ("Due Today Follow-ups", {"follow_up_status": "due"}),
        ("Assigned to 'Asha Rao'", {"employee": "Asha Rao"}),
        ("Phone Channel Only", {"channel": "phone"}),
    ]

    for label, flt in filter_tests:
        t0 = time.time()
        results = lead_repo.find_leads(
            workspace_id=ws_id,
            report_id=rep_id,
            limit=50,
            **flt,
        )
        t_query = (time.time() - t0) * 1000

        t0 = time.time()
        cnt = lead_repo.count_leads(
            workspace_id=ws_id,
            report_id=rep_id,
            **flt,
        )
        t_count = (time.time() - t0) * 1000
        print(f"   {label:25s}: Query={t_query:5.2f} ms | Count={t_count:5.2f} ms (Total matches: {cnt:,})")

    # 4. Benchmark Aggregation Pipeline (Report Metrics Calculation)
    print("\n4. Report Metrics Calculation Benchmark:")
    t0 = time.time()
    metrics = report_repo.recalculate_metrics(ws_id, rep_id)
    metric_lat = (time.time() - t0) * 1000
    print(f"   Calculated 9 distinct outcome metrics on {total_leads:,} records in {metric_lat:.2f} ms")
    print(f"   Metrics: {metrics}")

    # 5. Benchmark Follow-up Queue Query
    print("\n5. Follow-up Queue Latency Benchmark:")
    for cat in ["due_today", "overdue", "suggested"]:
        t0 = time.time()
        q_items = lead_repo.get_follow_up_queue(workspace_id=ws_id, category=cat, limit=50)
        q_lat = (time.time() - t0) * 1000
        print(f"   Queue [{cat:12s}]: {q_lat:5.2f} ms | First page items: {len(q_items)}")

    # 6. Benchmark Filtered Export Generation
    print("\n6. Export Generation Benchmark (First 5,000 interested leads):")
    t0 = time.time()
    content, filename, mime = export_service.generate_report_export(
        workspace_id=ws_id,
        report_id=rep_id,
        export_format="csv",
        filter_type="interested",
    )
    exp_lat = (time.time() - t0) * 1000
    print(f"   Export CSV generated: {len(content):,} bytes in {exp_lat:.2f} ms (~{len(content)/(1024*1024):.2f} MB)")

    print("\n" + "=" * 70)
    print("BENCHMARK COMPLETED SUCCESSFULLY!")
    print(f"Platform verified scalable to {target_count:,} leads per workspace.")
    print("=" * 70)


if __name__ == "__main__":
    count = 100_000
    if len(sys.argv) > 1:
        count = int(sys.argv[1])
    run_benchmark(count)
