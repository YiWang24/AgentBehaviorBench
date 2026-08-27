"""The agent's prompt files.

`agents_and_workflows.load_prompt` resolves `prompts/<name>.txt` relative to
two directories above its own module, which after installation is the
site-packages root. Shipping the prompts as a package puts them exactly there,
so upstream's path arithmetic works unchanged.
"""
