package cli

import (
	"bytes"
	"strings"
	"testing"

	"github.com/cruffinoni/update-all/internal/config"
	"github.com/cruffinoni/update-all/internal/updater"
)

func TestVersionAndHelp(t *testing.T) {
	for _, args := range [][]string{{"--version"}, {"--help"}} {
		cmd := NewRoot("9.8.7")
		var out bytes.Buffer
		cmd.SetOut(&out)
		cmd.SetErr(&out)
		cmd.SetArgs(args)
		if err := cmd.Execute(); err != nil {
			t.Fatal(err)
		}
		if args[0] == "--version" && !strings.Contains(out.String(), "update-all 9.8.7") {
			t.Fatalf("version output=%q", out.String())
		}
		if args[0] == "--help" && (!strings.Contains(out.String(), "update") || !strings.Contains(out.String(), "--jobs") || !strings.Contains(out.String(), "completion") || !strings.Contains(out.String(), "help")) {
			t.Fatalf("help output missing commands or flags: %q", out.String())
		}
	}
}

func TestRemovedFeaturesAreAbsent(t *testing.T) {
	cmd := NewRoot("9.8.7")
	for _, name := range []string{"force", "background", "no-background", "no-color", "no-colors", "install-agent"} {
		if cmd.Flags().Lookup(name) != nil {
			t.Errorf("removed flag --%s is still registered", name)
		}
	}
	for _, subcommand := range cmd.Commands() {
		if subcommand.Name() == "logs" {
			t.Error("removed logs command is still registered")
		}
	}
}

func TestFilterOnlySkipAndOS(t *testing.T) {
	all := []updater.Updater{{Label: "APT", RequiresOS: true}, {Label: "BREW"}, {Label: "NPM"}}
	got := filter(all, config.Options{Only: "APT,BREW", Skip: "APT", OS: true})
	if len(got) != 1 || got[0].Label != "BREW" {
		t.Fatalf("filtered labels=%v", got)
	}
	got = filter(all, config.Options{})
	if len(got) != 2 || got[0].Label != "BREW" || got[1].Label != "NPM" {
		t.Fatalf("default labels=%v", got)
	}
}
