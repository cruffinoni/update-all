package main

import (
	"fmt"
	"os"

	"github.com/cruffinoni/update-all/internal/cli"
)

// version is set by GoReleaser using ldflags.
var version = "3.0.0"

func main() {
	root := cli.NewRoot(version)
	if err := root.Execute(); err != nil {
		if cli.ExitCode(err) == 1 && err.Error() != "exit 1" {
			fmt.Fprintln(os.Stderr, "Error:", err)
		}
		os.Exit(cli.ExitCode(err))
	}
}
