// SPDX-License-Identifier: GPL-2.0
#include <generated/utsrelease.h>
#include <linux/cpumask.h>
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>

extern unsigned int __num_possible_cpus;

static int __init abk_bridge_test_init(void)
{
	pr_info("ABK bridge test: init on %s, possible cpus=%u\n",
		UTS_RELEASE, __num_possible_cpus);
	return 0;
}

static void __exit abk_bridge_test_exit(void)
{
	pr_info("ABK bridge test: exit\n");
}

module_init(abk_bridge_test_init);
module_exit(abk_bridge_test_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("OpenAI");
MODULE_DESCRIPTION("ABK dual ABI/KMI bridge test module");
