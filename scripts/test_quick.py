#!/usr/bin/env python3
"""
Quick test to see what's happening with Google Scholar
"""

from citationimpact import analyze_paper_impact

print("\n" + "="*60)
print("TEST 1: Try with a well-known paper (simpler title)")
print("="*60)

# Test with a well-known paper first
result = analyze_paper_impact(
    paper_title="Attention is all you need",
    data_source='google_scholar',
    max_citations=10,  # Just 10 for testing
    use_cache=False
)

print("\n" + "="*60)
print("RESULT:")
print("="*60)
if result.get('error'):
    print(f"Error: {result['error']}")
else:
    print(f"Success! Got {len(result.get('high_profile_scholars', []))} scholars")
    print(f"Citations analyzed: {result.get('analyzed_citations', 0)}")

print("\n" + "="*60)
print("TEST 2: Try with the ChatGPT paper")
print("="*60)

# Test with the paper that's failing
result2 = analyze_paper_impact(
    paper_title="Refining chatgpt-generated code",  # Shorter version
    data_source='google_scholar',
    max_citations=10,
    use_cache=False
)

print("\n" + "="*60)
print("RESULT:")
print("="*60)
if result2.get('error'):
    print(f"Error: {result2['error']}")
else:
    print(f"Success! Got {len(result2.get('high_profile_scholars', []))} scholars")
    print(f"Citations analyzed: {result2.get('analyzed_citations', 0)}")

