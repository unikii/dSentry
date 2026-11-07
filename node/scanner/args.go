package scanner

import (
	"fmt"
	"strings"
)

// splitCommandArgs handles the small shell-like syntax needed by smartctl
// configuration without invoking a shell.
func splitCommandArgs(input string) ([]string, error) {
	var args []string
	var current strings.Builder
	var quote rune
	escaped := false
	haveValue := false

	flush := func() {
		if haveValue {
			args = append(args, current.String())
			current.Reset()
			haveValue = false
		}
	}

	for _, r := range input {
		if escaped {
			current.WriteRune(r)
			haveValue = true
			escaped = false
			continue
		}
		if r == '\\' && quote != '\'' {
			escaped = true
			haveValue = true
			continue
		}
		if quote != 0 {
			if r == quote {
				quote = 0
			} else {
				current.WriteRune(r)
				haveValue = true
			}
			continue
		}
		if r == '\'' || r == '"' {
			quote = r
			haveValue = true
		} else if strings.ContainsRune(" \t\r\n", r) {
			flush()
		} else {
			current.WriteRune(r)
			haveValue = true
		}
	}

	if escaped {
		return nil, fmt.Errorf("trailing escape")
	}
	if quote != 0 {
		return nil, fmt.Errorf("unterminated quote")
	}
	flush()
	return args, nil
}
