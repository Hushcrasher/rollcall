"""`python manage.py load_dev_fixtures` — fake dataset for contributors.

Contributors have no access to the production parquet; this command gives
them a few hundred games, companies, users and contributions in one shot
(docs/02-ARCHITECTURE.md §6). Deterministic (fixed random seed) and
idempotent (get_or_create everywhere) — safe to re-run.

DEV ONLY: creates accounts with the password "devpassword" and a superuser
admin@example.com / "admin". Never run against a production database.
"""

import random
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from contributions.models import Contribution, Discipline
from games.models import Company, Engine, Game, GameCompany, GameEngine, GameGenre, Genre

GENRES = [
    "Action", "Adventure", "RPG", "Strategy", "Shooter", "Puzzle",
    "Platformer", "Racing", "Simulation", "Sports", "Indie", "Horror",
]  # fmt: skip

ENGINES = [
    "Unreal Engine", "Unity", "Godot", "GameMaker", "CryEngine",
    "Source", "RE Engine", "Frostbite", "In-house engine",
]  # fmt: skip

COMPANY_PARTS = (
    ["Iron", "Pixel", "Crimson", "Neon", "Silver", "Lunar", "Ember", "Frost",
     "Turbo", "Quantum", "Velvet", "Cobalt", "Golden", "Rogue", "Static"],
    ["Owl", "Forge", "Anvil", "Fox", "Raven", "Titan", "Harbor", "Peak",
     "Circuit", "Garden", "Beacon", "Falcon", "Atlas", "Comet", "Drift"],
    ["Studios", "Games", "Interactive", "Entertainment", "Works", "Collective"],
)  # fmt: skip

TITLE_PARTS = (
    ["Crimson", "Forgotten", "Endless", "Shattered", "Neon", "Silent",
     "Burning", "Frozen", "Hidden", "Iron", "Lost", "Savage", "Golden",
     "Hollow", "Wild", "Broken", "Astral", "Grim", "Radiant", "Feral"],
    ["Odyssey", "Kingdom", "Protocol", "Legacy", "Horizon", "Depths",
     "Frontier", "Requiem", "Vanguard", "Citadel", "Expanse", "Covenant",
     "Bastion", "Reckoning", "Ascent", "Dominion", "Paradox", "Exile",
     "Sanctum", "Overdrive"],
)  # fmt: skip

FIRST_NAMES = [
    "Alex", "Sam", "Jordan", "Casey", "Morgan", "Riley", "Quinn", "Avery",
    "Rowan", "Sasha", "Noor", "Yuki", "Mateo", "Ines", "Kofi", "Mina",
    "Leon", "Zara", "Hugo", "Ada",
]  # fmt: skip

LAST_NAMES = [
    "Reyes", "Kim", "Novak", "Dubois", "Tanaka", "Okafor", "Larsen",
    "Moreau", "Silva", "Haddad", "Kowalski", "Nguyen", "Berg", "Rossi",
    "Iyer", "Fontaine", "Weber", "Costa", "Andersson", "Petrov",
]  # fmt: skip

JOB_TITLES = {
    "Programming": ["Gameplay Programmer", "Engine Programmer", "Tools Programmer"],
    "Design": ["Game Designer", "Level Designer", "Narrative Designer"],
    "Art": ["3D Artist", "Concept Artist", "Technical Artist", "Art Director"],
    "Audio": ["Sound Designer", "Composer", "Audio Programmer"],
    "Production": ["Producer", "Associate Producer", "Project Manager"],
    "QA": ["QA Tester", "QA Lead", "QA Analyst"],
    "Writing": ["Writer", "Narrative Lead"],
    "Localization": ["Localization Specialist", "LQA Tester"],
    "Marketing/Publishing": ["Community Manager", "Marketing Manager"],
    "Business": ["Business Developer", "Licensing Manager"],
    "Support/Other": ["Player Support Agent", "IT Support"],
}  # fmt: skip


class Command(BaseCommand):
    help = "Load a deterministic fake dataset (games, companies, users, contributions). Dev only."

    def add_arguments(self, parser):
        parser.add_argument("--games", type=int, default=300)
        parser.add_argument("--users", type=int, default=40)
        parser.add_argument("--contributions", type=int, default=150)

    def handle(self, *args, **options):
        rng = random.Random(42)
        user_model = get_user_model()

        genres = [Genre.objects.get_or_create(name=name)[0] for name in GENRES]
        engines = [Engine.objects.get_or_create(name=name)[0] for name in ENGINES]
        disciplines = list(Discipline.objects.all())
        if not disciplines:
            raise SystemExit("Disciplines missing — run `manage.py migrate` first.")

        companies = self._create_companies(rng)
        games = self._create_games(rng, options["games"], genres, engines, companies)
        users = self._create_users(rng, options["users"], user_model)
        n_contribs = self._create_contributions(
            rng, options["contributions"], users, games, companies, disciplines
        )
        self._create_admin(user_model)

        self.stdout.write(
            self.style.SUCCESS(
                f"Dev fixtures ready: {len(games)} games, {len(companies)} companies, "
                f"{len(users)} users, {n_contribs} contributions. "
                "Superuser: admin@example.com / admin — "
                "members: devuserN@example.com / devpassword."
            )
        )

    def _create_companies(self, rng):
        companies = []
        seen = set()
        while len(companies) < 50:
            words = (rng.choice(part) for part in COMPANY_PARTS)
            name = " ".join(words)
            if name in seen:
                continue
            seen.add(name)
            company, _ = Company.objects.get_or_create(
                name=name, defaults={"source": Company.Source.MANUAL}
            )
            companies.append(company)
        return companies

    def _create_games(self, rng, count, genres, engines, companies):
        games = []
        seen = set()
        igdb_id = 1000
        steam_appid = 200000
        while len(games) < count:
            title = f"{rng.choice(TITLE_PARTS[0])} {rng.choice(TITLE_PARTS[1])}"
            if rng.random() < 0.25:
                title += f" {rng.randint(2, 4)}"
            if title in seen:
                continue
            seen.add(title)
            igdb_id += rng.randint(1, 9)
            steam_appid += rng.randint(10, 99)
            has_igdb = rng.random() < 0.85
            has_steam = rng.random() < 0.7 or not has_igdb
            # Draw ALL random values before get_or_create: the rng sequence
            # must be identical whether rows exist or not (idempotency).
            defaults = {
                "igdb_id": igdb_id if has_igdb else None,
                "steam_appid": steam_appid if has_steam else None,
                "release_date": date(rng.randint(1998, 2025), rng.randint(1, 12), 1),
                "summary": f"A {rng.choice(GENRES).lower()} game. (Dev fixture.)",
                "igdb_rating": rng.randint(40, 95) if has_igdb else None,
                "steam_positive_pct": rng.randint(35, 98) if has_steam else None,
                "steam_review_count": rng.randint(10, 50000) if has_steam else None,
                "source": Game.Source.MANUAL,
            }
            genre_picks = rng.sample(genres, k=rng.randint(1, 3))
            engine_picks = rng.sample(engines, k=rng.randint(1, 2))
            developer = rng.choice(companies)
            publisher = rng.choice(companies) if rng.random() < 0.6 else None

            game, created = Game.objects.get_or_create(title=title, defaults=defaults)
            games.append(game)
            if not created:
                continue
            for genre in genre_picks:
                GameGenre.objects.get_or_create(game=game, genre=genre)
            for engine in engine_picks:
                GameEngine.objects.get_or_create(game=game, engine=engine)
            GameCompany.objects.get_or_create(
                game=game, company=developer, role=GameCompany.Role.DEVELOPER
            )
            if publisher is not None:
                GameCompany.objects.get_or_create(
                    game=game, company=publisher, role=GameCompany.Role.PUBLISHER
                )
        return games

    def _create_users(self, rng, count, user_model):
        users = []
        for i in range(1, count + 1):
            display_name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            user, created = user_model.objects.get_or_create(
                email=f"devuser{i}@example.com",
                defaults={
                    "display_name": display_name,
                    "email_verified_at": timezone.now() if rng.random() < 0.9 else None,
                    "open_to_work": rng.random() < 0.3,
                    "contactable": rng.random() < 0.9,
                    "profile_public": rng.random() < 0.95,
                    "bio": "Game industry professional. (Dev fixture account.)",
                },
            )
            if created:
                user.set_password("devpassword")
                user.save(update_fields=["password"])
            users.append(user)
        return users

    def _create_contributions(self, rng, count, users, games, companies, disciplines):
        created_count = 0
        for _ in range(count):
            user = rng.choice(users)
            game = rng.choice(games)
            discipline = rng.choice(disciplines)
            start_year = rng.randint(2005, 2024)
            start = date(start_year, rng.randint(1, 12), 1)
            end = None
            if rng.random() < 0.75:
                end = date(start_year + rng.randint(0, 4), rng.randint(1, 12), 1)
                if end < start:
                    end = start
            _, created = Contribution.objects.get_or_create(
                user=user,
                game=game,
                discipline=discipline,
                start_date=start,
                defaults={
                    "company": rng.choice(companies) if rng.random() < 0.5 else None,
                    "job_title": rng.choice(JOB_TITLES[discipline.name]),
                    "end_date": end,
                },
            )
            created_count += int(created)
        return created_count

    def _create_admin(self, user_model):
        if not user_model.objects.filter(email="admin@example.com").exists():
            user_model.objects.create_superuser(
                email="admin@example.com",
                password="admin",
                display_name="Dev Admin",
            )
