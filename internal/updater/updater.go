package updater

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
)

type Spec struct {
	Executable  string
	VersionArgs []string
	Platforms   []string
	LoginShell  bool
}

type Updater struct {
	Label       string
	Description string
	Commands    []string
	Check       func() bool
	Sequential  bool
	RequiresOS  bool
	NeedsSudo   bool
	ErrorLines  int
	AutoAnswer  bool
}

var commandSpecs = map[string]Spec{
	"brew": {Executable: "brew", VersionArgs: []string{"--version"}}, "apt": {Executable: "apt"},
	"snap": {Executable: "snap"}, "flatpak": {Executable: "flatpak"},
	"mas":            {Executable: "mas", Platforms: []string{"darwin"}},
	"softwareupdate": {Executable: "softwareupdate", Platforms: []string{"darwin"}},
	"npm":            {Executable: "npm", VersionArgs: []string{"-v"}, LoginShell: true},
	"pnpm":           {Executable: "pnpm", VersionArgs: []string{"-v"}, LoginShell: true},
	"yarn":           {Executable: "yarn", VersionArgs: []string{"-v"}, LoginShell: true},
	"pipx":           {Executable: "pipx"}, "rustup": {Executable: "rustup"},
	"cargo-install-update": {Executable: "cargo-install-update"}, "asdf": {Executable: "asdf"},
	"mise": {Executable: "mise"}, "tailscale": {Executable: "tailscale"},
	"hermes": {Executable: "hermes"}, "claude": {Executable: "claude", VersionArgs: []string{"--version"}},
	"code": {Executable: "code", VersionArgs: []string{"--version"}, Platforms: []string{"darwin"}},
}

func (s Spec) Available() bool {
	if len(s.Platforms) > 0 {
		ok := false
		for _, platform := range s.Platforms {
			if runtime.GOOS == platform {
				ok = true
			}
		}
		if !ok {
			return false
		}
	}
	if s.LoginShell {
		return loginShellAvailable(s.Executable)
	}
	_, err := exec.LookPath(s.Executable)
	return err == nil
}

func Available(name string) bool { spec, ok := commandSpecs[name]; return ok && spec.Available() }

func loginShellAvailable(name string) bool {
	cmd := exec.Command("bash", "-lc", "export NVM_DIR=\"$HOME/.nvm\"; [ -s \"$NVM_DIR/nvm.sh\" ] && . \"$NVM_DIR/nvm.sh\" >/dev/null 2>&1; command -v \"$1\"", "update-all", name)
	return cmd.Run() == nil
}

func shellPrefix() string {
	return `export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1; `
}

func brewCommands() []string {
	commands := []string{"brew update", "brew upgrade"}
	if runtime.GOOS == "darwin" {
		commands = append(commands, "brew upgrade --cask --greedy")
	}
	return append(commands, "brew autoremove", "brew cleanup --prune=all", "brew doctor || true")
}

func yarnV1Present() bool {
	if !commandSpecs["yarn"].Available() {
		return false
	}
	cmd := exec.Command("bash", "-lc", shellPrefix()+"yarn --version")
	out, err := cmd.Output()
	if err != nil {
		return false
	}
	parts := strings.Split(strings.TrimSpace(string(out)), ".")
	major, err := strconv.Atoi(parts[0])
	return err == nil && major == 1
}

func All() []Updater {
	return []Updater{
		{Label: "BREW", Description: "Homebrew formulae & casks", Check: commandSpecs["brew"].Available, Sequential: true, Commands: brewCommands(), ErrorLines: 30, AutoAnswer: true},
		{Label: "APT", Description: "APT system packages", Check: commandSpecs["apt"].Available, Sequential: true, RequiresOS: true, NeedsSudo: true, Commands: []string{"sudo apt update", "sudo apt full-upgrade -y", "sudo apt autoremove -y", "sudo apt clean"}, ErrorLines: 20},
		{Label: "SNAP", Description: "Snap packages", Check: commandSpecs["snap"].Available, RequiresOS: true, NeedsSudo: true, Commands: []string{"sudo snap refresh"}, ErrorLines: 15},
		{Label: "FLATPAK", Description: "Flatpak packages", Check: commandSpecs["flatpak"].Available, Commands: []string{"flatpak update -y"}, ErrorLines: 15},
		{Label: "MAS", Description: "Mac App Store", Check: commandSpecs["mas"].Available, Commands: []string{"mas upgrade"}, ErrorLines: 10},
		{Label: "NPM", Description: "npm global packages", Check: commandSpecs["npm"].Available, Commands: []string{shellPrefix() + "npm update -g"}, ErrorLines: 20},
		{Label: "PNPM", Description: "pnpm global packages", Check: commandSpecs["pnpm"].Available, Commands: []string{shellPrefix() + "pnpm update -g"}, ErrorLines: 10},
		{Label: "YARN", Description: "Yarn global packages", Check: yarnV1Present, Commands: []string{shellPrefix() + "yarn global upgrade"}, ErrorLines: 15},
		{Label: "PIPX", Description: "pipx packages", Check: commandSpecs["pipx"].Available, Commands: []string{"pipx upgrade-all --include-injected"}, ErrorLines: 25},
		{Label: "RUST", Description: "Rust toolchain (rustup)", Check: commandSpecs["rustup"].Available, Commands: []string{"rustup self update && rustup update"}, ErrorLines: 15},
		{Label: "CARGO", Description: "Cargo-installed binaries", Check: commandSpecs["cargo-install-update"].Available, Commands: []string{"cargo install-update -a"}, ErrorLines: 30},
		{Label: "ASDF", Description: "asdf plugins", Check: commandSpecs["asdf"].Available, Commands: []string{"asdf update && asdf plugin-update --all"}, ErrorLines: 15},
		{Label: "MISE", Description: "mise toolchain", Check: commandSpecs["mise"].Available, Commands: []string{"mise self-update -y && mise upgrade -y"}, ErrorLines: 10},
		{Label: "TAILSCALE", Description: "Tailscale", Check: commandSpecs["tailscale"].Available, NeedsSudo: true, Commands: []string{"sudo tailscale update"}, ErrorLines: 15},
		{Label: "HERMES", Description: "Hermes Agent CLI", Check: commandSpecs["hermes"].Available, Commands: []string{"hermes update"}, ErrorLines: 15},
		{Label: "CLAUDE", Description: "Claude CLI", Check: commandSpecs["claude"].Available, Commands: []string{"claude update"}, ErrorLines: 10},
		{Label: "OMZ", Description: "Oh My Zsh", Check: func() bool {
			home, _ := os.UserHomeDir()
			info, err := os.Stat(filepath.Join(home, ".oh-my-zsh"))
			return err == nil && info.IsDir()
		}, Commands: []string{`RUNZSH=no CHSH=no KEEP_ZSHRC=yes env ZSH="$HOME/.oh-my-zsh" sh "$HOME/.oh-my-zsh/tools/upgrade.sh" || git -C "$HOME/.oh-my-zsh" pull --rebase --autostash`}, ErrorLines: 15},
	}
}

func VersionSpecs() []Spec {
	return []Spec{commandSpecs["brew"], {Executable: "node", VersionArgs: []string{"-v"}}, commandSpecs["npm"], commandSpecs["pnpm"], commandSpecs["yarn"], {Executable: "rustc", VersionArgs: []string{"-V"}}, {Executable: "go", VersionArgs: []string{"version"}}, {Executable: "python3", VersionArgs: []string{"--version"}}, commandSpecs["code"], commandSpecs["claude"]}
}

func (s Spec) VersionCommand() *exec.Cmd {
	args := append([]string{s.Executable}, s.VersionArgs...)
	if s.LoginShell {
		return exec.Command("bash", "-lc", shellPrefix()+strings.Join(args, " "))
	}
	return exec.Command(args[0], args[1:]...)
}

func (u Updater) String() string { return fmt.Sprintf("%s: %s", u.Label, u.Description) }
