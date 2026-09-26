# Contributing

Thanks for your interest in improving the AI Data Intelligence Platform!

## Quick start

1. Fork & clone:
   ```bash
   git clone https://github.com/<you>/data-intelligence-platform.git
   cd data-intelligence-platform
   ```
2. Set up:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Run dev server:
   ```bash
   python app.py
   ```
4. Run tests:
   ```bash
   python smoke_test.py
   python test_hang_fix.py
   ```

## Pull Request workflow

1. Create a feature branch:
   ```bash
   git checkout -b feature/<short-name>
   ```
2. Make focused commits:
   ```bash
   git commit -m "feat: add X"
   ```
3. Push & open a PR:
   ```bash
   git push origin feature/<short-name>
   ```

## Code style

- Python: PEP 8, max line length 120
- JS: modern ES2020+, no jQuery
- CSS: BEM-ish naming, dark-first theming with `[data-theme="light"]` overrides

## Commit conventions

We follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `style:` — formatting, no missing
- `refactor:` — code change that neither fixes a bug nor adds a feature
- `test:` — adding or fixing tests
- `chore:` — build, deps, tooling

## Adding a new data source

1. Implement a function in `data_intelligence/sources.py`:
   ```python
   def my_source(params: Dict[str, Any]) -> List[Dict[str, Any]]:
       # Return records following the standard schema:
       # { id, title, description, url, source, type, company, location, skills, industries, published_at, extra }
       ...
   ```
2. Register it in `SOURCE_REGISTRY`:
   ```python
   SOURCE_REGISTRY = {
       ...
       "my_source": my_source,
   }
   ```
3. Add it to `PERMITTED_SOURCES` for the appropriate data types in `workflow_builder.py`.

## Adding a new endpoint

1. Add the route in `app.py` with appropriate HTTP methods.
2. Add a corresponding client function in `static/js/app.js` (if frontend needs it).
3. Update `RUN_AND_TEST.md` with the test step.

## Reporting issues

Use GitHub Issues with:
- Clear title and description
- Steps to reproduce
- Expected vs actual behavior
- Screenshots if UI-related

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).