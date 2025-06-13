import {
    Button,
    makeStyles,
    Text,
    tokens,
    Menu,
    MenuTrigger,
    MenuPopover,
    MenuList,
    MenuItem,
    Avatar
} from '@fluentui/react-components';
import { Person24Regular, SignOut24Regular, Navigation24Regular } from '@fluentui/react-icons';
import { useAuth } from '../contexts/AuthContext';

// Add prop for toggling sidebar
interface HeaderProps {
    toggleSidebar?: () => void;
    isMobile?: boolean;
}

const useStyles = makeStyles({
    header: {
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0.5rem 1rem',
        borderBottom: `1px solid ${tokens.colorNeutralStroke1}`,
        backgroundColor: tokens.colorNeutralBackground1,
    },
    leftSection: {
        display: 'flex',
        alignItems: 'center',
        gap: '1rem',
    },
    logo: {
        fontWeight: 'bold',
        fontSize: tokens.fontSizeBase500,
    },
    nav: {
        display: 'flex',
        gap: '1rem',
    },
    navLink: {
        textDecoration: 'none',
        color: tokens.colorNeutralForeground1,
        padding: '0.5rem 0.75rem',
        borderRadius: '4px',
        '&:hover': {
            backgroundColor: tokens.colorNeutralBackground3,
        },
    },
    activeLink: {
        backgroundColor: tokens.colorNeutralBackground2,
        fontWeight: 'bold',
    },
    profileButton: {
        display: 'flex',
        alignItems: 'center',
        gap: '0.5rem',
    },
    menuButton: {
        marginRight: '1rem',
    }
});

export default function Header({ toggleSidebar, isMobile }: HeaderProps) {
    const classes = useStyles();
    const { user, logout } = useAuth();

    const handleLogout = () => {
        logout();
    };

    return (
        <header className={classes.header}>
            <div className={classes.leftSection}>
                {isMobile && toggleSidebar && (
                    <Button 
                        appearance="subtle"
                        icon={<Navigation24Regular />}
                        onClick={toggleSidebar}
                        className={classes.menuButton}
                        aria-label="Toggle chat list"
                    />
                )}
                <Text className={classes.logo}>Healthcare Agent Orchestrator</Text>
            </div>
            {user && (
                <Menu>
                    <MenuTrigger>
                        <Button
                            appearance="transparent"
                            className={classes.profileButton}
                            icon={<Avatar icon={<Person24Regular />} />}
                        >
                            {user.name || user.email || 'User'}
                        </Button>
                    </MenuTrigger>
                    <MenuPopover>
                        <MenuList>
                            <MenuItem icon={<SignOut24Regular />} onClick={handleLogout}>
                                Sign Out
                            </MenuItem>
                        </MenuList>
                    </MenuPopover>
                </Menu>
            )}
        </header>
    );
}
