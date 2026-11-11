import unittest
from unittest.mock import patch

import pet


class CarefulMoodTests(unittest.TestCase):
    def startle(self):
        st = {"mood": "idle", "since": 0, "line": 0}
        pet.set_mood(st, "startled", 100)
        return st

    def event(self, st, event, now, **data):
        with patch.object(pet, "read_stdin", return_value={"hook_event_name": event, **data}), \
             patch.object(pet, "load_state", return_value=st), \
             patch.object(pet, "save_state"), patch.object(pet.time, "time", return_value=now):
            pet.hook()

    def test_relaxes_without_new_hooks_at_exact_boundaries(self):
        st = self.startle()
        for now, mood in [(119.999, "startled"), (120, "careful"), (149.999, "careful"), (150, "working")]:
            with self.subTest(now=now):
                self.assertEqual(pet.base_mood(st, now)[:2], (mood, {"startled": 100, "careful": 120, "working": 150}[mood]))

    def test_normal_events_cannot_skip_or_restart_careful(self):
        st = self.startle()
        for now in [105, 120, 135, 149]:
            self.event(st, "PreToolUse", now)
        self.event(st, "Stop", 149, last_assistant_message="done")
        self.assertEqual(pet.base_mood(st, 149)[0], "careful")
        self.assertEqual(pet.base_mood(st, 150)[0], "working")
        self.event(st, "Stop", 150, last_assistant_message="done")
        self.assertEqual(pet.base_mood(st, 150)[0], "done")

    def test_uppercase_insult_and_correction_take_place_of_careful(self):
        for prompt, expected in [("YOU ARE USELESS", "defensive"), ("NO THAT IS WRONG", "embarrassed"), ("PLEASE CHECK THIS", "careful")]:
            with self.subTest(prompt=prompt):
                st = {"mood": "idle", "since": 0}
                self.event(st, "UserPromptSubmit", 100, prompt=prompt)
                self.assertEqual(pet.base_mood(st, 101)[0], "startled")
                self.assertEqual(pet.base_mood(st, 120)[0], expected)

    def test_pending_reaction_has_its_full_hold_after_startle(self):
        for reaction in ("defensive", "embarrassed"):
            with self.subTest(reaction=reaction):
                st = self.startle()
                pet.set_mood(st, reaction, 105)
                pet.set_mood(st, "working", 120)
                self.assertEqual(pet.base_mood(st, 120)[0], reaction)
                end = 120 + pet.HOLD[reaction]
                pet.set_mood(st, "working", end - .001)
                self.assertEqual(pet.base_mood(st, end - .001)[0], reaction)
                pet.set_mood(st, "working", end)
                self.assertEqual(pet.base_mood(st, end)[0], "working")

    def test_defensive_wins_regardless_of_reaction_order(self):
        for reactions in [("defensive", "embarrassed"), ("embarrassed", "defensive")]:
            with self.subTest(reactions=reactions):
                st = self.startle()
                for reaction in reactions:
                    pet.set_mood(st, reaction, 105)
                pet.set_mood(st, "startled", 110)
                self.assertEqual(pet.base_mood(st, 130)[0], "defensive")

    def test_active_reaction_survives_yelling_but_expired_one_does_not(self):
        for reaction in ("defensive", "embarrassed"):
            for elapsed in (1, pet.HOLD[reaction]):
                with self.subTest(reaction=reaction, elapsed=elapsed):
                    st = {"mood": "idle", "since": 0}
                    pet.set_mood(st, reaction, 100)
                    pet.set_mood(st, "startled", 100 + elapsed)
                    expected = reaction if elapsed < pet.HOLD[reaction] else "careful"
                    self.assertEqual(pet.base_mood(st, 120 + elapsed)[0], expected)

    def test_careful_yields_to_reactions_and_does_not_return_afterwards(self):
        for reaction in ("defensive", "embarrassed", "failed", "confused"):
            with self.subTest(reaction=reaction):
                st = self.startle()
                pet.set_mood(st, reaction, 121)
                self.assertEqual(pet.base_mood(st, 121)[0], reaction)
                pet.set_mood(st, "working", 121 + pet.HOLD[reaction])
                self.assertEqual(pet.base_mood(st, 121 + pet.HOLD[reaction])[0], "working")
                self.assertNotIn("after_startled", st)

    def test_old_saved_startled_state_recovers(self):
        st = {"mood": "startled", "since": 100, "until": 120, "line": 1}
        self.assertEqual(pet.base_mood(st, 120)[0], "careful")

    def test_each_pet_has_valid_distinct_careful_frames_and_dialogue(self):
        self.assertIn("careful", pet.load_lines())
        for name in pet.all_pets():
            with self.subTest(pet=name):
                art = pet.load_pet(name)["careful"]
                self.assertGreaterEqual(len({tuple(f) for f in art["frames"]}), 4)
                for frame in art["frames"]:
                    self.assertEqual(len(frame), 4)
                    self.assertTrue(all(len(row) <= pet.WIDTH for row in frame))
                for index in sum(art["order"], []):
                    self.assertTrue(0 <= index < len(art["frames"]))


if __name__ == "__main__":
    unittest.main()
