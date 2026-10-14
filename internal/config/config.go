package config

import (
	"strings"

	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

// Options is the resolved command configuration. Values can come from flags,
// UPDATE_ALL_* environment variables, or the defaults below, in that order.
type Options struct {
	OS   bool
	Jobs int
	Only string
	Skip string
}

func NewViper(cmd *cobra.Command) *viper.Viper {
	v := viper.New()
	v.SetEnvPrefix("UPDATE_ALL")
	v.SetEnvKeyReplacer(strings.NewReplacer("-", "_"))
	v.AutomaticEnv()
	v.SetDefault("jobs", 0)
	_ = v.BindPFlags(cmd.Flags())
	return v
}

func Load(v *viper.Viper) Options {
	return Options{
		OS: v.GetBool("os"), Jobs: v.GetInt("jobs"), Only: v.GetString("only"),
		Skip: v.GetString("skip"),
	}
}
