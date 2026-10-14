package config

import (
	"testing"

	"github.com/spf13/cobra"
)

func TestFlagOverridesEnvironment(t *testing.T) {
	t.Setenv("UPDATE_ALL_JOBS", "7")
	cmd := &cobra.Command{}
	cmd.Flags().Int("jobs", 0, "")
	if err := cmd.Flags().Set("jobs", "3"); err != nil {
		t.Fatal(err)
	}
	got := Load(NewViper(cmd))
	if got.Jobs != 3 {
		t.Fatalf("jobs = %d, want flag value 3", got.Jobs)
	}
}

func TestEnvironmentProvidesDefault(t *testing.T) {
	t.Setenv("UPDATE_ALL_SKIP", "APT,SNAP")
	cmd := &cobra.Command{}
	cmd.Flags().String("skip", "", "")
	got := Load(NewViper(cmd))
	if got.Skip != "APT,SNAP" {
		t.Fatalf("skip = %q, want APT,SNAP", got.Skip)
	}
}
