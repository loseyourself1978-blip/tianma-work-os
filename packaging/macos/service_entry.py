"""Closed frozen entry points; never execute arbitrary Python supplied by a caller."""
import sys

if len(sys.argv) > 1 and sys.argv[1] == "--twos-verify":
    from twos_runtime.builtin_verifier import main
    sys.argv.pop(1)
    main()
elif len(sys.argv) > 1 and sys.argv[1] == "--twos-sidecar":
    from twos_runtime.codex_exec_bridge import _command_line
    raise SystemExit(_command_line(sys.argv[2:]))
elif len(sys.argv) == 3 and sys.argv[1] == "--twos-iteration-check":
    from twos_runtime.iteration_candidate import check_main
    raise SystemExit(check_main(sys.argv[2:]))
elif len(sys.argv) > 1 and sys.argv[1] == "--twos-owner-recovery":
    from twos_runtime.desktop_owner_recovery import main
    raise SystemExit(main(sys.argv[2:]))
else:
    from twos_runtime.desktop import main
    raise SystemExit(main())
