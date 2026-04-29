import logging

def log_result(result, msg="", insert=False):
    key = "addResults" if insert else "updateResults"
    action = "added" if insert else "updated"

    successes = sum(1 for r in result[key] if r.get("success"))
    failures  = [r for r in result[key] if not r.get("success")]

    if msg != "":
        logging.debug(msg)

    logging.debug(f"{successes} {action}, {len(failures)} failed")
    if failures:
        logging.debug(f"Failures: {failures}")
        
def print_result(result, msg="", insert=False):
    key = "addResults" if insert else "updateResults"
    action = "added" if insert else "updated"

    successes = sum(1 for r in result[key] if r.get("success"))
    failures  = [r for r in result[key] if not r.get("success")]

    if msg != "":
        print(msg)

    print(f"{successes} {action}, {len(failures)} failed")
    if failures:
        print("Failures:", failures)