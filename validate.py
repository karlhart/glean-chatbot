"""
Validation script: runs a set of test questions against the live Glean pipeline
and checks that each returns a non-empty grounded answer from the correct datasource.

Usage:
    python validate.py

Each test prints PASS/FAIL and logs timing. Exit code 0 = all passed.
"""

import sys
import time
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from chatbot import ask

TEST_CASES = [
    {
        "question": "What is Lumina Stream Studios parental leave policy?",
        "expect_source_keywords": ["onboarding", "employee"],
        "description": "HR / benefits lookup",
    },
    {
        "question": "How do I get access to Box at Lumina?",
        "expect_source_keywords": ["onboarding", "legal", "contracts"],
        "description": "System access question",
    },
    {
        "question": "What is the VFX shot review process at Lumina?",
        "expect_source_keywords": ["post", "vfx", "production"],
        "description": "Post-production workflow",
    },
    {
        "question": "What happens if I lose my Lumina laptop?",
        "expect_source_keywords": ["security", "it"],
        "description": "IT security policy",
    },
    {
        "question": "What delivery format does Lumina use for the streaming platform?",
        "expect_source_keywords": ["delivery", "content", "streaming"],
        "description": "Content delivery standards",
    },
]


def run_tests() -> int:
    passed = 0
    failed = 0

    print("=" * 60)
    print("Lumina Chatbot — Validation Suite")
    print("=" * 60)

    for i, tc in enumerate(TEST_CASES, start=1):
        print(f"\n[{i}/{len(TEST_CASES)}] {tc['description']}")
        print(f"  Q: {tc['question']}")

        start = time.time()
        try:
            result = ask(tc["question"], top_k=5, include_citations=True)
            elapsed = time.time() - start

            answer = result["answer"]
            sources = result["sources"]

            # Basic checks
            has_answer = bool(answer and len(answer) > 20)
            has_sources = len(sources) > 0
            source_titles = " ".join(s["title"].lower() for s in sources)
            keyword_match = any(
                kw in source_titles for kw in tc["expect_source_keywords"]
            )

            if has_answer and has_sources and keyword_match:
                print(f"  ✓ PASS ({elapsed:.1f}s)")
                print(f"    Sources: {', '.join(s['title'] for s in sources[:2])}")
                print(f"    Answer preview: {answer[:120].strip()}...")
                passed += 1
            else:
                print(f"  ✗ FAIL ({elapsed:.1f}s)")
                if not has_answer:
                    print("    - Answer was empty or too short")
                if not has_sources:
                    print("    - No sources returned")
                if not keyword_match:
                    print(f"    - Expected keyword from {tc['expect_source_keywords']} in source titles")
                    print(f"    - Got: {source_titles[:120]}")
                failed += 1

        except Exception as e:
            elapsed = time.time() - start
            print(f"  ✗ ERROR ({elapsed:.1f}s): {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(TEST_CASES)} tests")
    print("=" * 60)
    return failed


if __name__ == "__main__":
    failures = run_tests()
    sys.exit(failures)
