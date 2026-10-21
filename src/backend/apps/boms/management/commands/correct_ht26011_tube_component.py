import json

from django.core.management.base import BaseCommand
from django.core.serializers.json import DjangoJSONEncoder

from apps.boms.ht26011_component_correction import correct_component


class Command(BaseCommand):
    help = "预检 HT26011 第二条管材更正为中交上下管；--apply 才写入，并保持业务数量不变。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--actor-employee")
        parser.add_argument("--expected-manifest", default="")

    def handle(self, *args, **options):
        result = correct_component(apply=options["apply"], actor_id=options["actor_employee"],
                                   expected_manifest=options["expected_manifest"])
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, cls=DjangoJSONEncoder))
