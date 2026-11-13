#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for kit_shell.py, the shared shell parser. Run: python3 -m unittest test_kit_shell.py"""

import os
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kit_shell as ks  # noqa: E402

CWD = "/work/project"


def argvs(command, cwd=CWD):
    return [list(c.argv) for c in ks.iter_commands(command, cwd)]


def progs(command):
    return [a[0] for a in argvs(command)]


class Operators(unittest.TestCase):
    def test_split_on_every_operator(self):
        self.assertEqual(argvs("a 1 && b 2 || c 3; d 4 | e 5 & f 6 |& g 7"),
                         [["a", "1"], ["b", "2"], ["c", "3"], ["d", "4"], ["e", "5"], ["f", "6"], ["g", "7"]])

    def test_newlines_separate(self):
        self.assertEqual(progs("a\nb\n\nc"), ["a", "b", "c"])

    def test_line_continuation_joins(self):
        self.assertEqual(argvs("git push \\\n  origin x"), [["git", "push", "origin", "x"]])

    def test_subshell_and_group(self):
        self.assertEqual(progs("(cd x && rm y); { rm z; }"), ["cd", "rm", "rm"])

    def test_control_flow_bodies(self):
        self.assertIn(["rm", "$f"], argvs('for f in *; do rm "$f"; done'))
        self.assertIn(["rm", "x"], argvs("if true; then rm x; else echo; fi"))
        self.assertIn(["rm", "x"], argvs("while false; do rm x; done"))


class Quoting(unittest.TestCase):
    def test_quoted_text_is_one_word(self):
        self.assertEqual(argvs('git commit -m "drop the rm call; and && more"'),
                         [["git", "commit", "-m", "drop the rm call; and && more"]])

    def test_single_quotes_are_literal(self):
        self.assertEqual(argvs("echo '$(rm x)' 'a\"b'"), [["echo", "$(rm x)", 'a"b']])

    def test_escapes(self):
        self.assertEqual(argvs('echo a\\ b "c\\"d"'), [["echo", "a b", 'c"d']])

    def test_adjacent_quotes_join(self):
        self.assertEqual(argvs("r'm' -rf x"), [["rm", "-rf", "x"]])

    def test_unbalanced_quotes_raise(self):
        for cmd in ('echo "abc', "echo 'abc", "echo $(abc", "echo `abc"):
            with self.subTest(cmd=cmd):
                with self.assertRaises(ks.ParseError):
                    list(ks.iter_commands(cmd, CWD))


class Comments(unittest.TestCase):
    def test_comment_dropped(self):
        self.assertEqual(argvs("echo a # rm x\nls"), [["echo", "a"], ["ls"]])

    def test_hash_inside_quotes_or_words_kept(self):
        self.assertEqual(argvs('echo "a # b" c#d'), [["echo", "a # b", "c#d"]])

    def test_comment_only_line(self):
        self.assertEqual(argvs("# rm -rf /\nls"), [["ls"]])


class Heredocs(unittest.TestCase):
    CMD = "cat > f <<'EOF'\nrm -rf /\ngit push --force\nEOF\nls"

    def test_body_is_not_parsed(self):
        self.assertEqual(progs(self.CMD), ["cat", "ls"])

    def test_body_is_returned(self):
        self.assertEqual(ks.heredoc_bodies(self.CMD), [("EOF", "rm -rf /\ngit push --force")])

    def test_commit_message_heredoc_in_substitution(self):
        cmd = "git commit -m \"$(cat <<'EOF'\nfix: rm stuff\n\nCo-Authored-By: x\nEOF\n)\""
        self.assertEqual(progs(cmd), ["cat", "git"])
        self.assertEqual(ks.heredoc_bodies(cmd), [("EOF", "fix: rm stuff\n\nCo-Authored-By: x")])

    def test_dash_and_double_quoted_tags(self):
        self.assertEqual(progs('cat <<-"END"\n\trm x\n\tEND\nls'), ["cat", "ls"])

    def test_here_string_is_not_a_heredoc(self):
        self.assertEqual(progs("cat <<<EOF\nrm x"), ["cat", "rm"])


class ReviewRegressions(unittest.TestCase):
    """Cases from the step A review: each was missed or mis-scoped by the first parser."""

    def test_nested_parse_error_does_not_hide_later_commands(self):
        self.assertIn(["rm", "-rf", "x"], argvs('bash -c "echo it\'s"; rm -rf x'))
        self.assertIn(["git", "reset", "--hard"], argvs('eval "echo it\'s"; git reset --hard'))

    def test_cd_in_a_subshell_or_pipeline_does_not_leak(self):
        cmds = list(ks.iter_commands("(cd /s; true); rm keep", CWD))
        self.assertEqual(cmds[-1].cwd, CWD)
        cmds = list(ks.iter_commands("cd /s | true; rm keep", CWD))
        self.assertEqual(cmds[-1].cwd, CWD)
        cmds = list(ks.iter_commands("(cd /s && rm a); cd /t; (rm b)", CWD))
        self.assertEqual([c.cwd for c in cmds if c.prog == "rm"], ["/s", "/t"])

    def test_heredoc_operator_inside_quotes_is_text(self):
        self.assertIn(["rm", "-rf", "x"], argvs('echo "use <<EOF in bash"\nrm -rf x'))
        self.assertIn(["rm", "y"], argvs("echo '<<EOF'\nrm y"))

    def test_heredoc_tags_with_dashes_and_dots(self):
        self.assertEqual(progs("cat <<END-DOC\nrm x\nEND-DOC\nrm y"), ["cat", "rm"])
        self.assertEqual(progs("cat <<'END-DOC'\nrm -rf is bad\nEND-DOC"), ["cat"])
        self.assertEqual(progs("cat <<v1.2\nrm x\nv1.2"), ["cat"])

    def test_arithmetic_shift_is_not_a_heredoc(self):
        self.assertEqual(progs("echo $((1<<2))\nrm y"), ["echo", "rm"])

    def test_shell_options_with_values(self):
        for cmd in ('bash -o pipefail -c "rm x"', 'bash -O extglob -c "rm x"', 'bash -e -o pipefail -c "rm x"'):
            with self.subTest(cmd=cmd):
                self.assertIn(["rm", "x"], argvs(cmd))

    def test_script_fed_to_a_shell(self):
        self.assertIn(["rm", "-rf", "build"], argvs("bash <<'EOF'\nrm -rf build\nEOF"))
        self.assertIn(["rm", "x"], argvs("sh -s <<EOF\nrm x\nEOF"))
        self.assertIn(["git", "reset", "--hard"], argvs('bash <<< "git reset --hard"'))
        self.assertNotIn(["rm", "x"], argvs("bash run.sh <<EOF\nrm x\nEOF"))  # stdin is data for run.sh
        self.assertNotIn(["rm", "x"], argvs("cat <<'EOF'\nrm x\nEOF"))

    def test_unquoted_heredoc_substitutions_run(self):
        self.assertIn(["rm", "-rf", "x"], argvs("cat <<EOF\n$(rm -rf x)\nEOF"))
        self.assertIn(["rm", "y"], argvs("cat <<EOF\n`rm y`\nEOF"))
        self.assertNotIn(["rm", "x"], argvs("cat <<'EOF'\n$(rm x)\nEOF"))
        self.assertNotIn(["rm", "x"], argvs("cat <<\\EOF\n$(rm x)\nEOF"))

    def test_heredoc_body_inside_substitution_kept(self):
        cmd = "git commit -m \"$(cat <<'EOF'\nsubject\n\nbody\nEOF\n)\""
        cmds = list(ks.iter_commands(cmd, CWD))
        self.assertEqual(cmds[0].heredocs, [("subject\n\nbody", True)])


class ReviewRound2(unittest.TestCase):
    def test_script_piped_into_a_shell(self):
        self.assertIn(["rm", "-rf", "build"], argvs("echo 'rm -rf build' | bash"))
        self.assertIn(["rm", "-rf", "build"], argvs("cat <<'X' | sh\nrm -rf build\nX"))
        self.assertIn(["rm", "x"], argvs("printf 'rm x\\n' | bash -s"))
        self.assertNotIn(["rm", "x"], argvs("echo 'rm x' | bash run.sh"))
        self.assertNotIn(["rm", "x"], argvs("echo 'rm x' | cat"))

    def test_clustered_shell_options(self):
        for cmd in ("bash -euo pipefail -c 'rm -rf build'", "bash -eo pipefail -c 'rm -rf build'",
                    "bash -e -o pipefail -O extglob -c 'rm -rf build'"):
            with self.subTest(cmd=cmd):
                self.assertIn(["rm", "-rf", "build"], argvs(cmd))

    def test_arithmetic_command_shift(self):
        self.assertEqual(progs("(( m = 1 << n ))\nrm -rf build")[-1], "rm")

    def test_unknown_cd_targets(self):
        for cmd in ("cd /s && cd - && rm a", 'cd /s && cd "$OLDPWD" && rm a', "cd /s && popd && rm a",
                    "cd ~- && rm a"):
            with self.subTest(cmd=cmd):
                self.assertFalse(list(ks.iter_commands(cmd, CWD))[-1].cwd_known)
        self.assertTrue(list(ks.iter_commands("cd /s && rm a", CWD))[-1].cwd_known)
        cmds = list(ks.iter_commands("cd /s & rm a", CWD))
        self.assertEqual(cmds[-1].cwd, CWD)  # a backgrounded cd runs in a subshell
        cmds = list(ks.iter_commands("pushd /s && rm a", CWD))
        self.assertEqual(cmds[-1].cwd, "/s")

    def test_function_keyword(self):
        self.assertIn(["rm", "-rf", "build"], argvs("function cleanup { rm -rf build; }; cleanup"))

    def test_ansi_c_quoting(self):
        self.assertIn(["rm", "-rf", "build"], argvs("rm -rf build; printf $'don\\'t\\n'"))
        self.assertEqual(argvs("echo $'a\\'b'"), [["echo", "a'b"]])

    def test_comment_inside_substitution(self):
        self.assertIn(["rm", "-rf", "build"], argvs("x=$(echo hi # it's\n)\nrm -rf build"))

    def test_stdin_texts(self):
        cmd = list(ks.iter_commands("python3 - <<'X'\nimport os\nX", CWD))[0]
        self.assertEqual(cmd.stdin, ["import os"])
        cmd = list(ks.iter_commands("echo 'print(1)' | python3", CWD))[-1]
        self.assertEqual(cmd.stdin, ["print(1)"])

    def test_interpreter_reads_stdin(self):
        yes = (["python3"], ["python3", "-"], ["python3", "-u", "-"], ["node"], ["node", "-"], ["perl"],
               ["ruby", "-w"])
        no = (["python3", "app.py"], ["python3", "-c", "x"], ["python3", "-m", "http.server"], ["node", "x.js"],
              ["node", "-e", "x"], ["ls"], [])
        for argv in yes:
            with self.subTest(argv=argv):
                self.assertTrue(ks.interpreter_reads_stdin(argv))
        for argv in no:
            with self.subTest(argv=argv):
                self.assertFalse(ks.interpreter_reads_stdin(argv))


class ReviewRound3(unittest.TestCase):
    def test_runners_are_unwrapped(self):
        for cmd, want in (("uv run python -c x", ["python", "-c", "x"]), ("poetry run pytest -q", ["pytest", "-q"]),
                          ("uv run --with rich python x.py", ["python", "x.py"]), ("pnpm exec tsc", ["tsc"]),
                          ("npx -y rimraf dist", ["rimraf", "dist"]), ("pipenv run rm x", ["rm", "x"])):
            with self.subTest(cmd=cmd):
                self.assertEqual(argvs(cmd)[-1], want)

    def test_xargs_and_find_exec_mark_operands_unknown(self):
        cmds = list(ks.iter_commands("ls | xargs git checkout --", CWD))
        self.assertTrue(cmds[-1].operands_unknown)
        cmds = list(ks.iter_commands("find . -exec git checkout {} \\;", CWD))
        self.assertTrue(cmds[-1].operands_unknown)
        self.assertFalse(list(ks.iter_commands("git checkout x", CWD))[0].operands_unknown)

    def test_submodule_foreach(self):
        self.assertIn(["git", "clean", "-fdx"], argvs("git submodule foreach --recursive git clean -fdx"))
        self.assertIn(["git", "reset", "--hard"], argvs("git submodule foreach 'git reset --hard'"))
        cmd = [c for c in ks.iter_commands("git submodule foreach 'rm x'", CWD) if c.prog == "rm"][0]
        self.assertFalse(cmd.cwd_known)

    def test_interpreter_mode(self):
        self.assertEqual(ks.interpreter_mode(["python3", "-c", "x"]), ("code", "x"))
        self.assertEqual(ks.interpreter_mode(["python3", "-"]), ("stdin", None))
        self.assertEqual(ks.interpreter_mode(["python3", "-m", "x"]), ("file", None))
        self.assertEqual(ks.interpreter_mode(["python3", "app.py"]), ("file", None))
        self.assertIsNone(ks.interpreter_mode(["ls"]))


class GitSplit(unittest.TestCase):
    def test_global_options(self):
        cases = {("status",): ("status", [], CWD), ("-C", "sub", "push", "origin"): ("push", ["origin"], CWD + "/sub"),
                 ("--git-dir=.git", "reset", "--hard"): ("reset", ["--hard"], CWD),
                 ("-c", "a=b", "--no-pager", "log"): ("log", [], CWD),
                 ("--super-prefix", "x", "push"): ("push", [], CWD), (): (None, [], CWD)}
        for args, want in cases.items():
            with self.subTest(args=args):
                self.assertEqual(ks.git_split(list(args), CWD), want)


class Substitutions(unittest.TestCase):
    def test_dollar_paren(self):
        self.assertEqual(argvs("echo $(rm x)")[0], ["rm", "x"])

    def test_dollar_paren_inside_double_quotes(self):
        self.assertEqual(argvs('echo "a $(rm x) b"')[0], ["rm", "x"])

    def test_nested(self):
        self.assertIn(["rm", "y"], argvs("echo $(echo $(rm y))"))

    def test_backticks(self):
        self.assertIn(["rm", "y"], argvs("x=`rm y`"))
        self.assertIn(["rm", "y"], argvs('echo "`rm y`"'))

    def test_process_substitution(self):
        self.assertIn(["rm", "a"], argvs("diff <(rm a) b"))

    def test_in_redirect_target(self):
        self.assertIn(["rm", "z"], argvs("echo hi > $(rm z)"))

    def test_parameter_expansion_is_not_a_command(self):
        self.assertEqual(argvs('echo "${HOME}/x"'), [["echo", "${HOME}/x"]])


class Recursion(unittest.TestCase):
    def test_bash_c(self):
        self.assertIn(["rm", "x"], argvs('bash -c "rm x; echo y"'))

    def test_combined_shell_flags(self):
        for cmd in ('bash -lc "rm x"', "sh -ec 'rm x'", 'zsh -c "rm x"', '/bin/bash -c "rm x"'):
            with self.subTest(cmd=cmd):
                self.assertIn(["rm", "x"], argvs(cmd))

    def test_shell_script_file_not_scanned(self):
        self.assertEqual(argvs("bash script.sh -c x"), [["bash", "script.sh", "-c", "x"]])

    def test_nested_bash_c(self):
        self.assertIn(["rm", "x"], argvs("bash -c \"sh -c 'rm x'\""))

    def test_eval(self):
        self.assertIn(["rm", "-rf", "x"], argvs('eval "rm -rf x"'))

    def test_xargs(self):
        for cmd in ("ls | xargs rm", "ls | xargs -n1 rm", "ls | xargs -I {} rm {}", "ls | xargs -0 -P 4 rm",
                    "ls | xargs --max-args=1 rm"):
            with self.subTest(cmd=cmd):
                self.assertEqual(argvs(cmd)[-1][0], "rm")

    def test_find_exec(self):
        self.assertIn(["rm", "{}"], argvs("find . -name '*.log' -exec rm {} \\;"))
        self.assertIn(["rm", "-f", "{}"], argvs("find . -exec rm -f {} +"))
        self.assertIn(["rm", "{}"], argvs("find . -execdir rm {} ';' -print"))

    def test_find_exec_shell(self):
        self.assertIn(["rm", "x"], argvs("find . -exec sh -c 'rm x' \\;"))

    def test_depth_is_bounded(self):
        cmd = "rm x"
        for _ in range(10):
            cmd = "bash -c %s" % ("'" + cmd.replace("'", "'\\''") + "'")
        list(ks.iter_commands(cmd, CWD))  # no error, no runaway recursion


class Prefixes(unittest.TestCase):
    def test_assignments(self):
        self.assertEqual(argvs("FOO=1 BAR=x rm a"), [["rm", "a"]])

    def test_wrappers(self):
        for cmd in ("env rm a", "env -i FOO=1 rm a", "env -u FOO rm a", "command rm a", "exec rm a", "nohup rm a",
                    "time rm a", "time -p rm a", "sudo rm a", "sudo -u root rm a", "sudo -E rm a", "nice rm a",
                    "nice -n 5 rm a", "nice -n5 rm a", "timeout 5 rm a", "timeout -s KILL 5s rm a",
                    "sudo env FOO=1 nice rm a"):
            with self.subTest(cmd=cmd):
                self.assertEqual(argvs(cmd), [["rm", "a"]])

    def test_env_split_string(self):
        self.assertEqual(argvs('env -S "rm a" b'), [["rm", "a", "b"]])

    def test_command_v_is_a_lookup(self):
        self.assertEqual(argvs("command -v rm"), [])

    def test_bare_assignment(self):
        self.assertEqual(argvs("FOO=bar"), [])


class Redirects(unittest.TestCase):
    def test_redirects_are_not_args(self):
        cmds = list(ks.iter_commands("cat < .env 2>/dev/null >> out.txt", CWD))
        self.assertEqual(list(cmds[0].argv), ["cat"])
        self.assertEqual([(op, str(t)) for op, t in cmds[0].redirects],
                         [("<", ".env"), ("2>", "/dev/null"), (">>", "out.txt")])

    def test_fd_duplication(self):
        cmds = list(ks.iter_commands("make 2>&1 | tee log", CWD))
        self.assertEqual(list(cmds[0].argv), ["make"])
        self.assertEqual(list(cmds[1].argv), ["tee", "log"])


class Cwd(unittest.TestCase):
    def test_cd_is_tracked(self):
        cmds = list(ks.iter_commands("cd sub && rm x; cd ../other; ls", CWD))
        self.assertEqual([c.cwd for c in cmds], [CWD, CWD + "/sub", CWD + "/sub", CWD + "/other"])

    def test_cd_absolute(self):
        self.assertEqual(list(ks.iter_commands("cd /tmp/x && ls", CWD))[1].cwd, "/tmp/x")

    def test_substitution_cd_does_not_leak(self):
        cmds = list(ks.iter_commands("echo $(cd sub) && ls", CWD))
        self.assertEqual(cmds[-1].cwd, CWD)


class InlineCode(unittest.TestCase):
    def test_interpreters(self):
        cases = [(["python3", "-c", "x"], "x"), (["python", "-c", "x"], "x"), (["python3.11", "-c", "x"], "x"),
                 (["node", "-e", "x"], "x"), (["node", "--eval", "x"], "x"), (["node", "--eval=x"], "x"),
                 (["node", "-p", "x"], "x"), (["ruby", "-e", "x"], "x"), (["perl", "-E", "x"], "x"),
                 (["python3", "-B", "-c", "x"], "x"), (["python3", "-cx"], "x"), (["python3", "-Bc", "x"], "x"),
                 (["python3", "-W", "ignore", "-c", "x"], "x"), (["perl", "-i", "-ne", "x"], "x"),
                 (["perl", "-pi", "-e", "x"], "x"), (["perl", "-ne", "x"], "x"), (["node", "-r", "dotenv/config",
                 "-e", "x"], "x"), (["deno", "eval", "x"], "x"), (["ruby", "-rjson", "-e", "x"], "x"),
                 (["node", "-pe", "x"], "x"), (["bun", "-pe", "x"], "x"), (["perl", "-le", "x"], "x"),
                 (["perl", "-lne", "x"], "x"), (["perl", "-0777ne", "x"], "x")]
        for argv, code in cases:
            with self.subTest(argv=argv):
                self.assertEqual(ks.inline_code(argv), code)

    def test_scripts_are_not_inline_code(self):
        for argv in (["python3", "script.py", "-c", "x"], ["node", "app.js"], ["ls", "-c", "x"], [],
                     ["python3", "-m", "pytest", "-c", "x"], ["python3", "-W", "ignore", "app.py"]):
            with self.subTest(argv=argv):
                self.assertIsNone(ks.inline_code(argv))


class Expansion(unittest.TestCase):
    def test_has_expansion(self):
        words = {w: ks.has_expansion(list(ks.iter_commands("x " + w, CWD))[-1].argv[1])
                 for w in ("a.txt", "*.log", "$HOME/x", "~/x", "`pwd`/x", "a{1,2}", "file?")}
        self.assertEqual(words, {"a.txt": False, "*.log": True, "$HOME/x": True, "~/x": True, "`pwd`/x": True,
                                 "a{1,2}": True, "file?": True})


if __name__ == "__main__":
    unittest.main()
