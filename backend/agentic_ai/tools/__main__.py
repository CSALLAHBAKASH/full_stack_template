import argparse
import json

from . import tools_by_name


def _parse_value(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a tool with positional values and optional keyword arguments."
    )
    parser.add_argument(
        "operation",
        choices=tools_by_name,
        help="Tool to run.",
    )
    parser.add_argument(
        "values",
        nargs="*",
        help="Positional tool values, in the order shown by the tool schema.",
    )
    parser.add_argument(
        "--kwargs",
        default="{}",
        metavar="JSON_OBJECT",
        help='Keyword arguments as JSON, e.g. \'{"precision": 2}\'.',
    )
    args = parser.parse_args()

    try:
        keyword_arguments = json.loads(args.kwargs)
    except json.JSONDecodeError as exc:
        parser.error(f"--kwargs must be valid JSON: {exc.msg}")
    if not isinstance(keyword_arguments, dict):
        parser.error("--kwargs must be a JSON object.")

    calculator = tools_by_name[args.operation]
    argument_names = list(calculator.args_schema.model_fields)
    if len(args.values) > len(argument_names):
        parser.error(
            f"{args.operation} accepts at most {len(argument_names)} positional values."
        )

    tool_arguments = {
        name: _parse_value(value)
        for name, value in zip(argument_names, args.values)
    }
    duplicate_arguments = tool_arguments.keys() & keyword_arguments.keys()
    if duplicate_arguments:
        parser.error(
            f"Argument {sorted(duplicate_arguments)[0]!r} was provided both positionally and in --kwargs."
        )
    tool_arguments.update(keyword_arguments)

    try:
        result = calculator.invoke(tool_arguments)
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(result)


if __name__ == "__main__":
    main()
