
        if session is not None:
            session_manager.end(call_id)
            session_manager.remove(call_id)

        await transport.cleanup()


if __name__ == "__main__":
    import uvicorn

    asyncio.run(main())
