"""`python manage.py seed_demo_people` — demo people with credits on REAL games.

Dev only. The game catalog comes from the real seed; this adds the "who worked
on them" side so person pages, game pages, search, and (above all) recruiter
search are populated with real games, engines, genres, and ratings.

Deterministic (fixed seed) and idempotent. Demo accounts: demoN@example.com,
password "demopass". Never run against production.
"""

import random
from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Company, Game, GameCompany

FIRST = [
    "Alex",
    "Sam",
    "Jordan",
    "Casey",
    "Morgan",
    "Riley",
    "Quinn",
    "Avery",
    "Rowan",
    "Sasha",
    "Noor",
    "Yuki",
    "Mateo",
    "Ines",
    "Kofi",
    "Mina",
    "Leon",
    "Zara",
    "Hugo",
]  # noqa: E501
LAST = [
    "Reyes",
    "Kim",
    "Novak",
    "Dubois",
    "Tanaka",
    "Okafor",
    "Larsen",
    "Moreau",
    "Silva",
    "Haddad",
    "Kowalski",
    "Nguyen",
    "Berg",
    "Rossi",
    "Iyer",
    "Fontaine",
    "Weber",
]  # noqa: E501
JOB_TITLES = {
    "Programming": ["Gameplay Programmer", "Engine Programmer", "Tools Programmer"],
    "Design": ["Game Designer", "Level Designer", "Narrative Designer"],
    "Art": ["3D Artist", "Concept Artist", "Technical Artist"],
    "Audio": ["Sound Designer", "Composer"],
    "Production": ["Producer", "Associate Producer"],
    "QA": ["QA Tester", "QA Lead"],
    "Writing": ["Writer", "Narrative Lead"],
    "Localization": ["Localization Specialist"],
    "Marketing/Publishing": ["Community Manager", "Marketing Manager"],
    "Business": ["Business Developer"],
    "Support/Other": ["Player Support Agent"],
}  # fmt: skip


class Command(BaseCommand):
    help = "Create demo people with credits on real games (dev only)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--people", type=int, default=40)
        parser.add_argument("--max-credits", type=int, default=6)

    def handle(self, *args: Any, **options: Any) -> None:
        rng = random.Random(7)
        disciplines = list(Discipline.objects.all())
        if not disciplines:
            raise SystemExit("Run migrations first (disciplines missing).")

        # Prefer recognizable, rated games (so the recruiter rating filter works);
        # cap the pool so we pick from well-known titles, not obscure ones.
        pool = list(
            Game.objects.filter(steam_positive_pct__isnull=False)
            .order_by("-steam_review_count")
            .values_list("pk", flat=True)[:3000]
        )
        if not pool:
            pool = list(Game.objects.values_list("pk", flat=True)[:3000])
        if not pool:
            raise SystemExit("No games found — seed the catalog first (seed_games).")

        created = 0
        for i in range(1, options["people"] + 1):
            user, is_new = User.objects.get_or_create(
                email=f"demo{i}@example.com",
                defaults={
                    "display_name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                    "email_verified_at": timezone.now(),
                    "open_to_work": rng.random() < 0.4,
                    "contactable": rng.random() < 0.85,
                    "bio": "Games industry professional. (Demo account.)",
                },
            )
            if is_new:
                user.set_password("demopass")
                user.save(update_fields=["password"])
                created += 1
                self._add_credits(rng, user, pool, disciplines, options["max_credits"])

        self.stdout.write(
            self.style.SUCCESS(
                f"{created} new demo people (demoN@example.com / demopass). "
                f"{Contribution.objects.filter(user__email__startswith='demo').count()} credits."
            )
        )

    def _add_credits(
        self,
        rng: random.Random,
        user: User,
        pool: list[int],
        disciplines: list[Discipline],
        max_credits: int,
    ) -> None:
        for game_pk in rng.sample(pool, k=min(rng.randint(1, max_credits), len(pool))):
            game = Game.objects.get(pk=game_pk)
            discipline = rng.choice(disciplines)
            start_year = rng.randint(2008, 2024)
            start = date(start_year, rng.randint(1, 12), 1)
            end = None
            if rng.random() < 0.7:
                end = date(min(start_year + rng.randint(1, 4), 2025), rng.randint(1, 12), 1)
                end = max(end, start)
            # Employer = one of the game's real studios, sometimes.
            employer: Company | None = None
            if rng.random() < 0.6:
                link = GameCompany.objects.filter(game=game).select_related("company").first()
                employer = link.company if link else None
            Contribution.objects.create(
                user=user,
                game=game,
                company=employer,
                discipline=discipline,
                job_title=rng.choice(JOB_TITLES[str(discipline.name)]),
                start_date=start,
                end_date=end,
            )
