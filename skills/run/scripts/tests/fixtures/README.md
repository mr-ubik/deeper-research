`quote_clean/` is a hand-written synthetic run directory. Mutation-focused
cases are constructed explicitly in `test_gates.py` and written to isolated
temporary run directories. Expected tallies are hand-computed beside their
assertions so tests never depend on archived run output.
