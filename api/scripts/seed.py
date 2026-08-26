"""Seed script to create a default demo user and sample research task."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure api directory is on sys.path
api_root = Path(__file__).resolve().parent.parent
if str(api_root) not in sys.path:
    sys.path.insert(0, str(api_root))

from sqlalchemy import select
from app.db import SessionLocal, init_db
from app.models import ResearchTask, Source, TaskEvent, TaskStatus, User
from app.security import hash_password


async def seed():
    print("Initializing database schema...")
    await init_db()

    async with SessionLocal() as session:
        # Check if demo user already exists
        email = "samuel@example.com"
        existing_user = await session.scalar(select(User).where(User.email == email))

        if not existing_user:
            print(f"Creating demo user: {email} (password: password123)...")
            user = User(
                email=email,
                hashed_password=hash_password("password123"),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            print(f"Demo user {email} already exists.")
            user = existing_user

        # Check if sample task exists
        existing_task = await session.scalar(
            select(ResearchTask).where(ResearchTask.user_id == user.id)
        )

        if not existing_task:
            print("Creating sample completed research task...")
            share_id = uuid.uuid4().hex
            task = ResearchTask(
                user_id=user.id,
                query="2026 Solid-State Battery Commercial Readiness & Production Timelines",
                status=TaskStatus.COMPLETE,
                plan=[
                    "Analyze solid-state electrolyte chemistries (sulfide, oxide, polymer)",
                    "Survey OEM pilot lines and production announcements (Toyota, QuantumScape, CATL)",
                    "Evaluate volumetric energy density vs current lithium-ion cell benchmarks",
                    "Synthesize manufacturing bottleneck challenges and commercial timeline",
                ],
                plan_edited_by_user=True,
                clarification_answers={
                    "Focus Area": "Commercial automotive scale and cell energy density"
                },
                report_markdown="""# 2026 Solid-State Battery Commercial Readiness & Production Timelines

Solid-state lithium batteries (SSBs) have transitioned from lab-scale cell prototypes to multi-megawatt pilot line validation in 2026 [1]. Leading automotive OEMs and battery manufacturers are targeting premium EV platform integration by 2027–2028, with mass-market cost parity anticipated post-2030.

## 1. Electrolyte Chemistry Landscapes
The industry has converged around two dominant solid-state electrolyte architectures:
- **Sulfide-based electrolytes (e.g., Argyrodite Li₆PS₅Cl)**: Offer high ionic conductivity (>10 mS/cm at room temperature) comparable to liquid electrolytes, making them the preferred choice for high-rate automotive applications [2].
- **Oxide ceramics (LLZO / LATP)**: Feature high thermal stability and chemical resistance against metallic lithium anodes, though interfacial contact resistance requires elevated manufacturing stack pressures.

## 2. OEM Production Timelines & Cell Density Benchmarks
Prototype automotive pouch cells featuring pure lithium-metal anodes have demonstrated volumetric energy densities exceeding **450 Wh/kg** and **1,050 Wh/L** [3], representing a ~40% volumetric improvement over tier-1 silicon-doped NMC955 lithium-ion cells.

- **Toyota / Idemitsu Kosan**: Operating a 200 MWh pilot manufacturing facility, targeting initial low-volume commercial vehicle integration in 2027.
- **QuantumScape (C-Sample validation)**: Scaling separator production with Cobra process line, demonstrating >1,000 deep cycles with 95% capacity retention.
- **CATL**: Expanding condensed/semi-solid battery production while ramping all-solid-state pilot lines.

## 3. Manufacturing Bottlenecks & Limitations
Key scaling challenges remain in interfacial impedance during high C-rate charging and dry-room atmospheric control for sulfide precursors [2]. Current cell costs remain 3.5x higher than conventional liquid lithium-ion cells on a per-kWh basis.

## Sources
1. https://nature.com/articles/s41560-026-solid-state - Nature Energy 2026 Solid-State Benchmark
2. https://battery-council.org/reports/2026-automotive-ssb - Automotive Battery Review 2026
3. https://energy.gov/eere/vehicles/solid-state-battery-rd - Department of Energy Cell Targets
""",
                share_id=share_id,
                is_public=True,
                input_tokens=1420,
                output_tokens=3890,
                searches_used=4,
                provider="anthropic",
                model="claude-opus-5",
                completed_at=datetime.now(timezone.utc),
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)

            # Add sample events
            events = [
                TaskEvent(
                    task_id=task.id,
                    kind="status",
                    message="Drafted 4-step research plan with human approval gate.",
                ),
                TaskEvent(
                    task_id=task.id,
                    kind="thought",
                    message="Plan approved by researcher. Commencing web searches across primary battery literature.",
                ),
                TaskEvent(
                    task_id=task.id,
                    kind="search",
                    message="Searching: solid-state battery pilot line capacity 2026",
                    data={"query": "solid-state battery pilot line capacity 2026"},
                ),
                TaskEvent(
                    task_id=task.id,
                    kind="search",
                    message="Searching: sulfide vs oxide solid electrolyte ionic conductivity",
                    data={"query": "sulfide vs oxide solid electrolyte ionic conductivity"},
                ),
                TaskEvent(
                    task_id=task.id,
                    kind="status",
                    message="Synthesized full markdown report with 3 cited references.",
                ),
            ]
            session.add_all(events)

            # Add sample sources
            sources = [
                Source(
                    task_id=task.id,
                    url="https://nature.com/articles/s41560-026-solid-state",
                    title="Nature Energy — Solid-State Battery Commercialization Report",
                    snippet="Review of 2026 pilot line milestones, lithium-metal dendrite suppression, and cycle life metrics across sulfide cell chemistries.",
                    excluded=False,
                ),
                Source(
                    task_id=task.id,
                    url="https://battery-council.org/reports/2026-automotive-ssb",
                    title="Global Battery Council 2026 Automotive Outlook",
                    snippet="Supply chain analysis of dry separator coating processes, stack pressures, and OEM vehicle integration targets for 2027-2030.",
                    excluded=False,
                ),
                Source(
                    task_id=task.id,
                    url="https://energy.gov/eere/vehicles/solid-state-battery-rd",
                    title="DOE Vehicle Technologies Office — Advanced Battery Targets",
                    snippet="Technical roadmap targeting >450 Wh/kg gravimetric energy density and fast charging within 15 minutes for next-generation solid-state cells.",
                    excluded=False,
                ),
            ]
            session.add_all(sources)
            await session.commit()
            print("Sample research task successfully seeded!")

    print("\n✅ Database seeded successfully.")
    print("👉 You can log in immediately with:")
    print("   Email:    samuel@example.com")
    print("   Password: password123\n")


if __name__ == "__main__":
    asyncio.run(seed())

