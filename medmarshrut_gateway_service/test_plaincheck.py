"""Fact check of a plain-words text against the physician's conclusion: no network, no assistant."""
from __future__ import annotations

import unittest

from plaincheck import preservation

LUNG = ("В S6 правого лёгкого определяется солидный узел 7×6 мм. Заключение: солидный узел правого лёгкого. "
        "Рекомендована консультация пульмонолога, контрольная КТ через 6–12 месяцев.")


class PreservationTests(unittest.TestCase):
    def test_retelling_with_all_facts_passes(self):
        plain = ("В правом лёгком, в сегменте S6, нашли небольшой узелок 7 на 6 мм. Врач советует сходить к пульмонологу "
                 "и через 6-12 месяцев сделать повторную КТ.")
        check = preservation(LUNG, plain)
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["kept"], ["7×6 мм", "6–12 месяцев", "справа", "S6", "пульмонолог", "контрольное исследование"])

    def test_lost_and_new_facts_are_named(self):
        check = preservation(LUNG, "В лёгком нашли узелок 8 мм, слева. Сходите к онкологу.")
        self.assertFalse(check["ok"])
        self.assertEqual(check["missing"], ["7×6 мм", "6–12 месяцев", "справа", "S6", "пульмонолог", "контрольное исследование"])
        self.assertEqual(check["added"], ["8 мм", "слева", "онколог"])

    def test_side_words_are_not_confused_with_rules(self):
        check = preservation("Узел 5 мм. Наблюдение по правилам клиники.", "Узел 5 мм, наблюдаем по правилам клиники.")
        self.assertTrue(check["ok"], check)

    def test_birads_and_decimals(self):
        conclusion = "Справа образование, BI-RADS 4. КТИ 0,56. Консультация онколога-маммолога."
        self.assertTrue(preservation(conclusion, "Справа есть образование, категория BI-RADS 4, индекс 0,56. Нужен онколог-маммолог.")["ok"])
        self.assertEqual(preservation(conclusion, "Справа образование, BI-RADS 3, индекс 0,56, онколог-маммолог.")["missing"],
                         ["4", "BI-RADS 4"])


if __name__ == "__main__":
    unittest.main()
