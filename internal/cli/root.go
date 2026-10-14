package cli

import (
	"errors"
	"fmt"
	"os"
	"runtime"
	"strings"
	"syscall"
	"time"

	"github.com/cruffinoni/update-all/internal/agent"
	"github.com/cruffinoni/update-all/internal/config"
	"github.com/cruffinoni/update-all/internal/runner"
	"github.com/cruffinoni/update-all/internal/selfupdate"
	"github.com/cruffinoni/update-all/internal/updater"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewRoot(version string) *cobra.Command {
	var uninstallAgent, noOS bool
	var v *viper.Viper
	root := &cobra.Command{
		Use: "update-all", Version: version, Short: "Update package managers and developer tools",
		SilenceUsage: true, SilenceErrors: true,
		RunE: func(cmd *cobra.Command, args []string) error {
			if len(args) > 0 {
				return fmt.Errorf("unexpected arguments: %s", strings.Join(args, " "))
			}
			if uninstallAgent {
				return agent.Uninstall()
			}
			options := config.Load(v)
			if noOS {
				options.OS = false
			}
			return run(options, version)
		},
	}
	root.SetVersionTemplate("{{.Name}} {{.Version}}\n")
	root.Flags().Bool("os", false, "Include OS system updates (sudo may be required depending on the packages updated)")
	root.Flags().BoolVar(&noOS, "no-os", false, "Do not include OS system updates")
	root.Flags().Int("jobs", 0, "Maximum number of parallel workers")
	root.Flags().String("only", "", "Run only these comma-separated updater labels")
	root.Flags().String("skip", "", "Skip these comma-separated updater labels")
	root.Flags().BoolVar(&uninstallAgent, "uninstall-agent", false, "Remove a previously installed scheduler")
	v = config.NewViper(root)
	root.AddCommand(newUpdateCommand())
	return root
}

func newUpdateCommand() *cobra.Command {
	return &cobra.Command{Use: "update", Short: "Update update-all from GitHub Releases", Args: cobra.NoArgs, RunE: func(cmd *cobra.Command, args []string) error {
		if err := selfupdate.Update(); err != nil {
			return err
		}
		fmt.Println("update-all updated successfully.")
		return nil
	}}
}

type exitError struct{ code int }

func (e *exitError) Error() string { return fmt.Sprintf("exit %d", e.code) }

func run(options config.Options, version string) error {
	if runner.IsTerminal() && os.Getenv(selfupdate.SkipEnv) == "" {
		if update, declined := selfupdate.AskUpdate(version); update {
			if err := selfupdate.Update(); err == nil {
				exe, e := os.Executable()
				if e == nil {
					env := append(os.Environ(), selfupdate.SkipEnv+"=1")
					return syscall.Exec(exe, os.Args, env)
				}
			} else {
				fmt.Println("⚠ Self-update failed — continuing with the current version.")
			}
		} else if declined != "" {
			if err := selfupdate.MarkDeclined(declined); err != nil {
				fmt.Printf("⚠ Could not record declined version: %v\n", err)
			}
			fmt.Println("Run 'update-all update' to update later.")
		}
	}
	jobs := options.Jobs
	if jobs <= 0 {
		jobs = runtime.NumCPU()
		if jobs > 6 {
			jobs = 6
		}
		if jobs < 1 {
			jobs = 4
		}
	}
	fmt.Printf("update-all  ·  %d workers", jobs)
	if options.OS {
		fmt.Print("  ·  os on")
	}
	fmt.Println()
	fmt.Println()
	started := time.Now()
	all := updater.All()
	selected := filter(all, options)
	sequential, parallel := []updater.Updater{}, []updater.Updater{}
	needsSudo := false
	for _, u := range selected {
		if u.Sequential {
			sequential = append(sequential, u)
		} else {
			parallel = append(parallel, u)
		}
		if u.NeedsSudo && u.Check() {
			needsSudo = true
		}
	}
	var osUpdater *updater.Updater
	if options.OS {
		key := "apt"
		if runtime.GOOS == "darwin" {
			key = "softwareupdate"
		}
		commands, supported := runner.OSCommands()
		if supported && updater.Available(key) {
			u := updater.Updater{Label: "OS", Description: "system updates", Commands: commands, Check: func() bool { return true }, Sequential: true, NeedsSudo: true, ErrorLines: 20}
			osUpdater = &u
			needsSudo = true
		}
	}
	broker := &runner.Broker{}
	if needsSudo {
		fmt.Println("⚠ sudo required — enter your password once:")
		if err := runner.VerifySudo(broker, func(line string) { fmt.Println("  " + line) }); err != nil {
			return fmt.Errorf("sudo authentication failed — aborting before running any updaters: %w", err)
		}
	}
	seqResults := runner.RunSequential(sequential, broker, func(s string) { fmt.Println(s) })
	parResults := runner.RunParallel(parallel, jobs, broker)
	osResults := []runner.Result{}
	if osUpdater != nil {
		osResults = runner.RunSequential([]updater.Updater{*osUpdater}, broker, func(s string) { fmt.Println(s) })
	}
	results := append(append(seqResults, parResults...), osResults...)
	runner.PrintFailures(results)
	_, fail := runner.ResultsSummary(results)
	elapsed := time.Since(started)
	runner.PrintSummary(results, elapsed)
	fmt.Println()
	fmt.Println("Versions")
	runner.PrintVersions(func(s string) { fmt.Println(s) })
	if fail > 0 {
		return &exitError{code: 1}
	}
	return nil
}

func filter(all []updater.Updater, options config.Options) []updater.Updater {
	only := labels(options.Only)
	skip := labels(options.Skip)
	out := make([]updater.Updater, 0, len(all))
	for _, u := range all {
		if u.RequiresOS && !options.OS {
			continue
		}
		if len(only) > 0 && !only[u.Label] {
			continue
		}
		if skip[u.Label] {
			continue
		}
		out = append(out, u)
	}
	return out
}
func labels(s string) map[string]bool {
	out := map[string]bool{}
	for _, label := range strings.Split(s, ",") {
		label = strings.ToUpper(strings.TrimSpace(label))
		if label != "" {
			out[label] = true
		}
	}
	return out
}
func ExitCode(err error) int {
	var exit *exitError
	if errors.As(err, &exit) {
		return exit.code
	}
	if err != nil {
		return 1
	}
	return 0
}
