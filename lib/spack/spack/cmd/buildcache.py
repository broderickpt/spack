# Copyright 2013-2020 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import os
import shutil
import sys

import llnl.util.tty as tty
import spack.binary_distribution as bindist
import spack.cmd
import spack.cmd.common.arguments as arguments
import spack.environment as ev
import spack.hash_types as ht
import spack.mirror
import spack.relocate
import spack.repo
import spack.spec
import spack.store
import spack.config
import spack.repo
import spack.store
import spack.util.url as url_util

from spack.error import SpecError
from spack.spec import Spec, save_dependency_spec_yamls

from spack.cmd import display_specs

description = "create, download and install binary packages"
section = "packaging"
level = "long"


def setup_parser(subparser):
    setup_parser.parser = subparser
    subparsers = subparser.add_subparsers(help='buildcache sub-commands')

    create = subparsers.add_parser('create', help=createtarball.__doc__)
    create.add_argument('-r', '--rel', action='store_true',
                        help="make all rpaths relative" +
                             " before creating tarballs.")
    create.add_argument('-f', '--force', action='store_true',
                        help="overwrite tarball if it exists.")
    create.add_argument('-u', '--unsigned', action='store_true',
                        help="create unsigned buildcache" +
                             " tarballs for testing")
    create.add_argument('-a', '--allow-root', action='store_true',
                        help="allow install root string in binary files " +
                             "after RPATH substitution")
    create.add_argument('-k', '--key', metavar='key',
                        type=str, default=None,
                        help="Key for signing.")
    output = create.add_mutually_exclusive_group(required=True)
    output.add_argument('-d', '--directory',
                        metavar='directory',
                        type=str,
                        help="directory where " +
                             "buildcaches will be written.")
    output.add_argument('-m', '--mirror_name',
                        metavar='mirror_name',
                        type=str,
                        help="mirror name where " +
                             "buildcaches will be written.")
    output.add_argument('--mirror_url',
                        metavar='mirror_url',
                        type=str,
                        help="mirror url where " +
                             "buildcaches will be written.")
    create.add_argument('--no-rebuild-index', action='store_true',
                        default=False, help="skip rebuilding index after " +
                                            "building package(s)")
    create.add_argument('-y', '--spec-yaml', default=None,
                        help='Create buildcache entry for spec from yaml file')
    create.add_argument('--no-deps', action='store_true', default='false',
                        help='Create buildcache entry wo/ dependencies')
    arguments.add_common_arguments(create, ['specs'])
    create.set_defaults(func=createtarball)

    install = subparsers.add_parser('install', help=installtarball.__doc__)
    install.add_argument('-f', '--force', action='store_true',
                         help="overwrite install directory if it exists.")
    install.add_argument('-m', '--multiple', action='store_true',
                         help="allow all matching packages ")
    install.add_argument('-a', '--allow-root', action='store_true',
                         help="allow install root string in binary files " +
                              "after RPATH substitution")
    install.add_argument('-u', '--unsigned', action='store_true',
                         help="install unsigned buildcache" +
                              " tarballs for testing")
    arguments.add_common_arguments(install, ['specs'])
    install.set_defaults(func=installtarball)

    listcache = subparsers.add_parser('list', help=listspecs.__doc__)
    arguments.add_common_arguments(listcache, ['long', 'very_long'])
    listcache.add_argument('-v', '--variants',
                           action='store_true',
                           dest='variants',
                           help='show variants in output (can be long)')
    listcache.add_argument('-f', '--force', action='store_true',
                           help="force new download of specs")
    listcache.add_argument('-a', '--allarch', action='store_true',
                           help="list specs for all available architectures" +
                                 " instead of default platform and OS")
    arguments.add_common_arguments(listcache, ['specs'])
    listcache.set_defaults(func=listspecs)

    dlkeys = subparsers.add_parser('keys', help=getkeys.__doc__)
    dlkeys.add_argument(
        '-i', '--install', action='store_true',
        help="install Keys pulled from mirror")
    dlkeys.add_argument(
        '-t', '--trust', action='store_true',
        help="trust all downloaded keys")
    dlkeys.add_argument('-f', '--force', action='store_true',
                        help="force new download of keys")
    dlkeys.set_defaults(func=getkeys)

    preview_parser = subparsers.add_parser(
        'preview',
        help='analyzes an installed spec and reports whether '
             'executables and libraries are relocatable'
    )
    arguments.add_common_arguments(preview_parser, ['installed_specs'])
    preview_parser.set_defaults(func=preview)

    # Check if binaries need to be rebuilt on remote mirror
    check = subparsers.add_parser('check', help=check_binaries.__doc__)
    check.add_argument(
        '-m', '--mirror-url', default=None,
        help='Override any configured mirrors with this mirror url')

    check.add_argument(
        '-o', '--output-file', default=None,
        help='File where rebuild info should be written')

    # used to construct scope arguments below
    scopes = spack.config.scopes()
    scopes_metavar = spack.config.scopes_metavar

    check.add_argument(
        '--scope', choices=scopes, metavar=scopes_metavar,
        default=spack.config.default_modify_scope(),
        help="configuration scope containing mirrors to check")

    check.add_argument(
        '-s', '--spec', default=None,
        help='Check single spec instead of release specs file')

    check.add_argument(
        '-y', '--spec-yaml', default=None,
        help='Check single spec from yaml file instead of release specs file')

    check.add_argument(
        '--rebuild-on-error', default=False, action='store_true',
        help="Default to rebuilding packages if errors are encountered " +
             "during the process of checking whether rebuilding is needed")

    check.set_defaults(func=check_binaries)

    # Download tarball and spec.yaml
    dltarball = subparsers.add_parser('download', help=get_tarball.__doc__)
    dltarball.add_argument(
        '-s', '--spec', default=None,
        help="Download built tarball for spec from mirror")
    dltarball.add_argument(
        '-y', '--spec-yaml', default=None,
        help="Download built tarball for spec (from yaml file) from mirror")
    dltarball.add_argument(
        '-p', '--path', default=None,
        help="Path to directory where tarball should be downloaded")
    dltarball.add_argument(
        '-c', '--require-cdashid', action='store_true', default=False,
        help="Require .cdashid file to be downloaded with buildcache entry")
    dltarball.set_defaults(func=get_tarball)

    # Get buildcache name
    getbuildcachename = subparsers.add_parser('get-buildcache-name',
                                              help=get_buildcache_name.__doc__)
    getbuildcachename.add_argument(
        '-s', '--spec', default=None,
        help='Spec string for which buildcache name is desired')
    getbuildcachename.add_argument(
        '-y', '--spec-yaml', default=None,
        help='Path to spec yaml file for which buildcache name is desired')
    getbuildcachename.set_defaults(func=get_buildcache_name)

    # Given the root spec, save the yaml of the dependent spec to a file
    saveyaml = subparsers.add_parser('save-yaml',
                                     help=save_spec_yamls.__doc__)
    saveyaml.add_argument(
        '--root-spec', default=None,
        help='Root spec of dependent spec')
    saveyaml.add_argument(
        '--root-spec-yaml', default=None,
        help='Path to yaml file containing root spec of dependent spec')
    saveyaml.add_argument(
        '-s', '--specs', default=None,
        help='List of dependent specs for which saved yaml is desired')
    saveyaml.add_argument(
        '-y', '--yaml-dir', default=None,
        help='Path to directory where spec yamls should be saved')
    saveyaml.set_defaults(func=save_spec_yamls)

    # Copy buildcache from some directory to another mirror url
    copy = subparsers.add_parser('copy', help=buildcache_copy.__doc__)
    copy.add_argument(
        '--base-dir', default=None,
        help='Path to mirror directory (root of existing buildcache)')
    copy.add_argument(
        '--spec-yaml', default=None,
        help='Path to spec yaml file representing buildcache entry to copy')
    copy.add_argument(
        '--destination-url', default=None,
        help='Destination mirror url')
    copy.set_defaults(func=buildcache_copy)

    # Update buildcache index without copying any additional packages
    update_index = subparsers.add_parser(
        'update-index', help=buildcache_update_index.__doc__)
    update_index.add_argument(
        '-d', '--mirror-url', default=None, help='Destination mirror url')
    update_index.set_defaults(func=buildcache_update_index)


def find_matching_specs(pkgs, allow_multiple_matches=False, env=None):
    """Returns a list of specs matching the not necessarily
       concretized specs given from cli

    Args:
        specs: list of specs to be matched against installed packages
        allow_multiple_matches : if True multiple matches are admitted

    Return:
        list of specs
    """
    hashes = env.all_hashes() if env else None

    # List of specs that match expressions given via command line
    specs_from_cli = []
    has_errors = False
    tty.debug('find_matching_specs: about to parse specs for {0}'.format(pkgs))
    specs = spack.cmd.parse_specs(pkgs)
    for spec in specs:
        matching = spack.store.db.query(spec, hashes=hashes)
        # For each spec provided, make sure it refers to only one package.
        # Fail and ask user to be unambiguous if it doesn't
        if not allow_multiple_matches and len(matching) > 1:
            tty.error('%s matches multiple installed packages:' % spec)
            for match in matching:
                tty.msg('"%s"' % match.format())
            has_errors = True

        # No installed package matches the query
        if len(matching) == 0 and spec is not any:
            tty.error('{0} does not match any installed packages.'.format(
                spec))
            has_errors = True

        specs_from_cli.extend(matching)
    if has_errors:
        tty.die('use one of the matching specs above')

    return specs_from_cli


def match_downloaded_specs(pkgs, allow_multiple_matches=False, force=False):
    """Returns a list of specs matching the not necessarily
       concretized specs given from cli

    Args:
        specs: list of specs to be matched against buildcaches on mirror
        allow_multiple_matches : if True multiple matches are admitted

    Return:
        list of specs
    """
    # List of specs that match expressions given via command line
    specs_from_cli = []
    has_errors = False
    allarch = False
    specs = bindist.get_specs(force, allarch)
    for pkg in pkgs:
        matches = []
        tty.msg("buildcache spec(s) matching %s \n" % pkg)
        for spec in sorted(specs):
            if pkg.startswith('/'):
                pkghash = pkg.replace('/', '')
                if spec.dag_hash().startswith(pkghash):
                    matches.append(spec)
            else:
                if spec.satisfies(pkg):
                    matches.append(spec)
        # For each pkg provided, make sure it refers to only one package.
        # Fail and ask user to be unambiguous if it doesn't
        if not allow_multiple_matches and len(matches) > 1:
            tty.error('%s matches multiple downloaded packages:' % pkg)
            for match in matches:
                tty.msg('"%s"' % match.format())
            has_errors = True

        # No downloaded package matches the query
        if len(matches) == 0:
            tty.error('%s does not match any downloaded packages.' % pkg)
            has_errors = True

        specs_from_cli.extend(matches)
    if has_errors:
        tty.die('use one of the matching specs above')

    return specs_from_cli


def _createtarball(env, spec_yaml, packages, output_location, key,
                   no_deps, force, rel, unsigned, allow_root,
                   no_rebuild_index):
    if spec_yaml:
        packages = set()
        with open(spec_yaml, 'r') as fd:
            yaml_text = fd.read()
            tty.debug('createtarball read spec yaml:')
            tty.debug(yaml_text)
            s = Spec.from_yaml(yaml_text)
            packages.add('/{0}'.format(s.dag_hash()))

    elif packages:
        packages = packages

    else:
        tty.die("build cache file creation requires at least one" +
                " installed package argument or else path to a" +
                " yaml file containing a spec to install")
    pkgs = set(packages)
    specs = set()

    mirror = spack.mirror.MirrorCollection().lookup(output_location)
    outdir = url_util.format(mirror.push_url)

    msg = 'Buildcache files will be output to %s/build_cache' % outdir
    tty.debug(msg)

    signkey = None
    if key:
        signkey = key

    matches = find_matching_specs(pkgs, env=env)

    if matches:
        tty.debug('Found at least one matching spec')

    for match in matches:
        tty.debug('examining match {0}'.format(match.format()))
        if match.external or match.virtual:
            tty.debug('skipping external or virtual spec %s' %
                      match.format())
        else:
            tty.debug('adding matching spec %s' % match.format())
            specs.add(match)
            if no_deps is True:
                continue
            tty.debug('recursing dependencies')
            for d, node in match.traverse(order='post',
                                          depth=True,
                                          deptype=('link', 'run')):
                if node.external or node.virtual:
                    tty.debug('skipping external or virtual dependency %s' %
                              node.format())
                else:
                    tty.debug('adding dependency %s' % node.format())
                    specs.add(node)

    for spec in specs:
        tty.msg('creating binary cache file for package %s ' % spec.format())
        try:
            bindist.build_tarball(spec, outdir, force, rel,
                                  unsigned, allow_root, signkey,
                                  not no_rebuild_index)
        except Exception as e:
            tty.warn('%s' % e)
            pass


def createtarball(args):
    """create a binary package from an existing install"""

    # restrict matching to current environment if one is active
    env = ev.get_env(args, 'buildcache create')

    output_location = None
    if args.directory:
        output_location = args.directory
    elif args.mirror_name:
        output_location = args.mirror_name
    elif args.mirror_url:
        output_location = args.mirror_url

    _createtarball(env, args.spec_yaml, args.specs, output_location,
                   args.key, args.no_deps, args.force, args.rel, args.unsigned,
                   args.allow_root, args.no_rebuild_index)


def installtarball(args):
    """install from a binary package"""
    if not args.specs:
        tty.die("build cache file installation requires" +
                " at least one package spec argument")
    pkgs = set(args.specs)
    matches = match_downloaded_specs(pkgs, args.multiple, args.force)

    for match in matches:
        install_tarball(match, args)


def install_tarball(spec, args):
    s = Spec(spec)
    if s.external or s.virtual:
        tty.warn("Skipping external or virtual package %s" % spec.format())
        return
    for d in s.dependencies(deptype=('link', 'run')):
        tty.msg("Installing buildcache for dependency spec %s" % d)
        install_tarball(d, args)
    package = spack.repo.get(spec)
    if s.concrete and package.installed and not args.force:
        tty.warn("Package for spec %s already installed." % spec.format())
    else:
        tarball = bindist.download_tarball(spec)
        if tarball:
            tty.msg('Installing buildcache for spec %s' % spec.format())
            bindist.extract_tarball(spec, tarball, args.allow_root,
                                    args.unsigned, args.force)
            spack.hooks.post_install(spec)
            spack.store.db.add(spec, spack.store.layout)
        else:
            tty.die('Download of binary cache file for spec %s failed.' %
                    spec.format())


def listspecs(args):
    """list binary packages available from mirrors"""
    specs = bindist.get_specs(args.force, args.allarch)
    if args.specs:
        constraints = set(args.specs)
        specs = [s for s in specs if any(s.satisfies(c) for c in constraints)]
    display_specs(specs, args, all_headers=True)


def getkeys(args):
    """get public keys available on mirrors"""
    bindist.get_keys(args.install, args.trust, args.force)


def preview(args):
    """Print a status tree of the selected specs that shows which nodes are
    relocatable and which might not be.

    Args:
        args: command line arguments
    """
    specs = find_matching_specs(args.specs, allow_multiple_matches=True)

    # Cycle over the specs that match
    for spec in specs:
        print("Relocatable nodes")
        print("--------------------------------")
        print(spec.tree(status_fn=spack.relocate.is_relocatable))


def check_binaries(args):
    """Check specs (either a single spec from --spec, or else the full set
    of release specs) against remote binary mirror(s) to see if any need
    to be rebuilt.  This command uses the process exit code to indicate
    its result, specifically, if the exit code is non-zero, then at least
    one of the indicated specs needs to be rebuilt.
    """
    if args.spec or args.spec_yaml:
        specs = [get_concrete_spec(args)]
    else:
        env = ev.get_env(args, 'buildcache', required=True)
        env.concretize()
        specs = env.all_specs()

    if not specs:
        tty.msg('No specs provided, exiting.')
        sys.exit(0)

    for spec in specs:
        spec.concretize()

    # Next see if there are any configured binary mirrors
    configured_mirrors = spack.config.get('mirrors', scope=args.scope)

    if args.mirror_url:
        configured_mirrors = {'additionalMirrorUrl': args.mirror_url}

    if not configured_mirrors:
        tty.msg('No mirrors provided, exiting.')
        sys.exit(0)

    sys.exit(bindist.check_specs_against_mirrors(
        configured_mirrors, specs, args.output_file, args.rebuild_on_error))


def download_buildcache_files(concrete_spec, local_dest, require_cdashid,
                              mirror_url=None):
    tarfile_name = bindist.tarball_name(concrete_spec, '.spack')
    tarball_dir_name = bindist.tarball_directory_name(concrete_spec)
    tarball_path_name = os.path.join(tarball_dir_name, tarfile_name)
    local_tarball_path = os.path.join(local_dest, tarball_dir_name)

    files_to_fetch = [
        {
            'url': tarball_path_name,
            'path': local_tarball_path,
            'required': True,
        }, {
            'url': bindist.tarball_name(concrete_spec, '.spec.yaml'),
            'path': local_dest,
            'required': True,
        }, {
            'url': bindist.tarball_name(concrete_spec, '.cdashid'),
            'path': local_dest,
            'required': require_cdashid,
        },
    ]

    return bindist.download_buildcache_entry(files_to_fetch, mirror_url)


def get_tarball(args):
    """Download buildcache entry from a remote mirror to local folder.  This
    command uses the process exit code to indicate its result, specifically,
    a non-zero exit code indicates that the command failed to download at
    least one of the required buildcache components.  Normally, just the
    tarball and .spec.yaml files are required, but if the --require-cdashid
    argument was provided, then a .cdashid file is also required."""
    if not args.spec and not args.spec_yaml:
        tty.msg('No specs provided, exiting.')
        sys.exit(0)

    if not args.path:
        tty.msg('No download path provided, exiting')
        sys.exit(0)

    spec = get_concrete_spec(args)
    result = download_buildcache_files(spec, args.path, args.require_cdashid)

    if not result:
        sys.exit(1)


def get_concrete_spec(args):
    spec_str = args.spec
    spec_yaml_path = args.spec_yaml

    if not spec_str and not spec_yaml_path:
        tty.msg('Must provide either spec string or path to ' +
                'yaml to concretize spec')
        sys.exit(1)

    if spec_str:
        try:
            spec = Spec(spec_str)
            spec.concretize()
        except SpecError as spec_error:
            tty.error('Unable to concrectize spec {0}'.format(args.spec))
            tty.debug(spec_error)
            sys.exit(1)

        return spec

    with open(spec_yaml_path, 'r') as fd:
        return Spec.from_yaml(fd.read())


def get_buildcache_name(args):
    """Get name (prefix) of buildcache entries for this spec"""
    spec = get_concrete_spec(args)
    buildcache_name = bindist.tarball_name(spec, '')

    print('{0}'.format(buildcache_name))

    sys.exit(0)


def save_spec_yamls(args):
    """Get full spec for dependencies, relative to root spec, and write them
    to files in the specified output directory.  Uses exit code to signal
    success or failure.  An exit code of zero means the command was likely
    successful.  If any errors or exceptions are encountered, or if expected
    command-line arguments are not provided, then the exit code will be
    non-zero."""
    if not args.root_spec and not args.root_spec_yaml:
        tty.msg('No root spec provided, exiting.')
        sys.exit(1)

    if not args.specs:
        tty.msg('No dependent specs provided, exiting.')
        sys.exit(1)

    if not args.yaml_dir:
        tty.msg('No yaml directory provided, exiting.')
        sys.exit(1)

    if args.root_spec_yaml:
        with open(args.root_spec_yaml) as fd:
            root_spec_as_yaml = fd.read()
    else:
        root_spec = Spec(args.root_spec)
        root_spec.concretize()
        root_spec_as_yaml = root_spec.to_yaml(hash=ht.build_hash)

    save_dependency_spec_yamls(
        root_spec_as_yaml, args.yaml_dir, args.specs.split())

    sys.exit(0)


def buildcache_copy(args):
    """Copy a buildcache entry and all its files from one mirror, given as
    '--base-dir', to some other mirror, specified as '--destination-url'.
    The specific buildcache entry to be copied from one location to the
    other is identified using the '--spec-yaml' argument."""
    # TODO: This sub-command should go away once #11117 is merged

    if not args.spec_yaml:
        tty.msg('No spec yaml provided, exiting.')
        sys.exit(1)

    if not args.base_dir:
        tty.msg('No base directory provided, exiting.')
        sys.exit(1)

    if not args.destination_url:
        tty.msg('No destination mirror url provided, exiting.')
        sys.exit(1)

    dest_url = args.destination_url

    if dest_url[0:7] != 'file://' and dest_url[0] != '/':
        tty.msg('Only urls beginning with "file://" or "/" are supported ' +
                'by buildcache copy.')
        sys.exit(1)

    try:
        with open(args.spec_yaml, 'r') as fd:
            spec = Spec.from_yaml(fd.read())
    except Exception as e:
        tty.debug(e)
        tty.error('Unable to concrectize spec from yaml {0}'.format(
            args.spec_yaml))
        sys.exit(1)

    dest_root_path = dest_url
    if dest_url[0:7] == 'file://':
        dest_root_path = dest_url[7:]

    build_cache_dir = bindist.build_cache_relative_path()

    tarball_rel_path = os.path.join(
        build_cache_dir, bindist.tarball_path_name(spec, '.spack'))
    tarball_src_path = os.path.join(args.base_dir, tarball_rel_path)
    tarball_dest_path = os.path.join(dest_root_path, tarball_rel_path)

    specfile_rel_path = os.path.join(
        build_cache_dir, bindist.tarball_name(spec, '.spec.yaml'))
    specfile_src_path = os.path.join(args.base_dir, specfile_rel_path)
    specfile_dest_path = os.path.join(dest_root_path, specfile_rel_path)

    cdashidfile_rel_path = os.path.join(
        build_cache_dir, bindist.tarball_name(spec, '.cdashid'))
    cdashid_src_path = os.path.join(args.base_dir, cdashidfile_rel_path)
    cdashid_dest_path = os.path.join(dest_root_path, cdashidfile_rel_path)

    # Make sure directory structure exists before attempting to copy
    os.makedirs(os.path.dirname(tarball_dest_path))

    # Now copy the specfile and tarball files to the destination mirror
    tty.msg('Copying {0}'.format(tarball_rel_path))
    shutil.copyfile(tarball_src_path, tarball_dest_path)

    tty.msg('Copying {0}'.format(specfile_rel_path))
    shutil.copyfile(specfile_src_path, specfile_dest_path)

    # Copy the cdashid file (if exists) to the destination mirror
    if os.path.exists(cdashid_src_path):
        tty.msg('Copying {0}'.format(cdashidfile_rel_path))
        shutil.copyfile(cdashid_src_path, cdashid_dest_path)


def buildcache_update_index(args):
    """Update a buildcache index."""
    outdir = '.'
    if args.mirror_url:
        outdir = args.mirror_url

    mirror = spack.mirror.MirrorCollection().lookup(outdir)
    outdir = url_util.format(mirror.push_url)

    bindist.generate_package_index(
        url_util.join(outdir, bindist.build_cache_relative_path()))


def buildcache(parser, args):
    if args.func:
        args.func(args)
