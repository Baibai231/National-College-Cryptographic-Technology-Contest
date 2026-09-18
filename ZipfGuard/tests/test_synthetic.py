import unittest

from core.synthetic import (
    aggregate_synthetic_counts,
    aligned_train_validation_counts,
    generate_synthetic_dataset,
    passwords_for_split,
)


class SyntheticDatasetTests(unittest.TestCase):
    def test_generation_is_deterministic_and_split_is_disjoint(self):
        first = generate_synthetic_dataset(size=1_000, seed=17)
        second = generate_synthetic_dataset(size=1_000, seed=17)
        different = generate_synthetic_dataset(size=1_000, seed=18)
        self.assertEqual(first, second)
        self.assertNotEqual(
            [row["password"] for row in first["records"]],
            [row["password"] for row in different["records"]],
        )
        ids = {
            split: {row["user_id"] for row in first["records"] if row["split"] == split}
            for split in ("train", "validation", "test")
        }
        self.assertEqual([len(ids[name]) for name in ("train", "validation", "test")], [600, 200, 200])
        self.assertFalse(ids["train"] & ids["validation"])
        self.assertFalse(ids["train"] & ids["test"])
        self.assertFalse(ids["validation"] & ids["test"])

    def test_aggregation_and_aligned_counts_use_the_same_users(self):
        dataset = generate_synthetic_dataset(size=1_000, seed=19)
        aggregate = aggregate_synthetic_counts(dataset)
        original, training, validation = aligned_train_validation_counts(dataset)
        self.assertEqual(aggregate["total_count"], 1_000)
        self.assertEqual(int(training.sum()), 600)
        self.assertEqual(int(validation.sum()), 200)
        self.assertEqual(int(original.sum()), 800)
        self.assertEqual(len(passwords_for_split(dataset, "test")), 200)


if __name__ == "__main__":
    unittest.main()
