from langfuse import get_client


def smoke_test():

    langfuse = get_client()

    # check my langfuse credentials via auth_check
    if langfuse.auth_check():
        print("Langfuse client is authenticated and ready!")
    else:
        raise RuntimeError(
            "Authentication failed. Please check your credentials and host.")

    # span with context manager
    with langfuse.start_as_current_observation(as_type="span", name="fpl.trace-smoke") as span:
        # span.input = "hello"
        span.update(input="hello")
        span.update(output="connection works")

    langfuse.flush()
