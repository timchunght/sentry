import React from 'react';
import ConfigStore from '../../stores/configStore';
import OrganizationState from '../../mixins/organizationState';
import {Link} from 'react-router';

import Broadcasts from './broadcasts';
import StatusPage from './statuspage';
import UserNav from './userNav';
import requiredAdminActions from '../requiredAdminActions';
import OrganizationSelector from './organizationSelector';
import {t} from '../../locale';

const Header = React.createClass({
  mixins: [OrganizationState],

  render() {
    let user = ConfigStore.get('user');
    let logo;

    if (user) {
      logo = <span className="icon-sentry-logo"/>;
    } else {
      logo = <span className="icon-sentry-logo-full"/>;
    }

    let org = this.getOrganization();
    let actionMessage = null;

    if (org) {
      let requiredActions = org.requiredAdminActions;
      if (requiredActions.length > 0) {
        if (this.getAccess().has('org:write')) {
          let slugId = requiredActions[0].toLowerCase().replace(/_/g, '-');
          let url = `/organizations/${org.slug}/actions/${slugId}/`;
          actionMessage = (
            <a href={url}>{t('Required Action:')}{' '}{
              requiredAdminActions[requiredActions[0]].getActionLinkTitle()}</a>
          );
        } else {
          actionMessage = (
            <span>{t('There are pending actions for an administrator of this organization!')}</span>
          );
        }
      }
    }

    // NOTE: this.props.orgId not guaranteed to be specified
    return (
      <header>
        <div className="container">
          <UserNav className="pull-right" />
          <Broadcasts className="pull-right" />
          {this.props.orgId ?
            <Link to={`/${this.props.orgId}/`} className="logo">{logo}</Link>
            :
            <a href="/" className="logo">{logo}</a>
          }
          <OrganizationSelector organization={this.getOrganization()} className="pull-right" />
          <StatusPage className="pull-right" />
          {actionMessage ?
            <span className="admin-action-message">{actionMessage}</span>
            : null}
        </div>
      </header>
    );
  }
});

export default Header;
