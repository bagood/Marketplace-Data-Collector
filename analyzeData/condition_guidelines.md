# Phone Condition Rating Guidelines

> This is a placeholder guideline. Replace or refine these rules as the rating
> policy develops.

Rate only what is explicitly stated in the advertisement description. Do not
assume that missing information means the phone is damaged or flawless.

## Ratings

- **Excellent** — Described as like new, flawless, rarely used, or explicitly
  free from scratches, dents, cracks, functional defects, and repairs.
- **Good** — Fully functional with only minor cosmetic wear, such as light or
  hairline scratches, and no significant damage.
- **Fair** — Usable but has notable wear, reduced battery health, repaired or
  replaced components, dents, scratches, or another disclosed moderate issue.
- **Poor** — Cracked, badly damaged, locked, non-functional, sold for parts, or
  has a major defect affecting normal use.
- **Unknown** — The description is missing, is a wanted/buying advertisement,
  or does not provide enough evidence to rate the phone's physical and
  functional condition.

## Output rules

1. Return exactly one rating from: `Excellent`, `Good`, `Fair`, `Poor`, or
   `Unknown`.
2. Give a brief reason grounded only in the description.
3. Do not treat marketing phrases as proof when they do not describe condition.
4. When evidence conflicts, use the worse condition supported by the text.
