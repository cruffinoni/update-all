package updater

import (
	"reflect"
	"testing"
)

func TestCatalogLabelsAndExecutionPasses(t *testing.T) {
	all := All()
	want := []string{"BREW", "APT", "SNAP", "FLATPAK", "MAS", "NPM", "PNPM", "YARN", "PIPX", "RUST", "CARGO", "ASDF", "MISE", "TAILSCALE", "HERMES", "CLAUDE", "OMZ"}
	got := make([]string, 0, len(all))
	sequential := []string{}
	for _, item := range all {
		got = append(got, item.Label)
		if item.Sequential {
			sequential = append(sequential, item.Label)
		}
		if item.Check == nil || len(item.Commands) == 0 || item.Description == "" {
			t.Fatalf("incomplete updater %q", item.Label)
		}
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("labels = %v, want %v", got, want)
	}
	if !reflect.DeepEqual(sequential, []string{"BREW", "APT"}) {
		t.Fatalf("sequential = %v", sequential)
	}
}

func TestBrewCommands(t *testing.T) {
	commands := brewCommands()
	if len(commands) < 5 || commands[0] != "brew update" || commands[len(commands)-1] != "brew doctor || true" {
		t.Fatalf("unexpected brew commands: %v", commands)
	}
}
