import unittest
from phi_atelier import ArtBrief, compile_brief


class PhiAtelierTests(unittest.TestCase):
    def test_three_original_directions(self):
        output = compile_brief(ArtBrief(concept="An impossible city", symbolism="Time folding over itself"))
        self.assertEqual(output["schema_version"], "phi.atelier.prompt-bundle.v1")
        self.assertEqual(output["render_status"], "not_rendered")
        self.assertEqual(len(output["candidates"]), 3)
        self.assertEqual([c["id"] for c in output["candidates"]], ["monumental", "intimate", "recursive"])
        self.assertIn("Time folding", output["candidates"][0]["positive_prompt"])

    def test_weighting_and_exclusions(self):
        output = compile_brief(ArtBrief(concept="A new universe", influences={"escher": 3, "dali": 0, "picasso": 1}))
        self.assertEqual([s["name"] for s in output["style_grammar"]], ["escher", "picasso"])
        self.assertEqual([s["weight_percent"] for s in output["style_grammar"]], [75.0, 25.0])

    def test_determinism(self):
        brief = ArtBrief(concept="A glass forest", orientation="square")
        self.assertEqual(compile_brief(brief), compile_brief(brief))

    def test_input_validation(self):
        for brief in [
            ArtBrief(concept=""),
            ArtBrief(concept="x", orientation="cinemascope"),
            ArtBrief(concept="x", influences={"dali": 0}),
            ArtBrief(concept="x", influences={"unknown": 2}),
            ArtBrief(concept="x", influences={"escher": -1}),
            ArtBrief(concept="x", influences={"escher": True}),
        ]:
            with self.subTest(brief=brief), self.assertRaises(ValueError):
                compile_brief(brief)


if __name__ == "__main__":
    unittest.main()
